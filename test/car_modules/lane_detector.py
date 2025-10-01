import cv2
import numpy as np
import math

class LaneDetector:
    def __init__(self):
        # --- 차선 검출 파라미터 (제어용) ---
        self.ROI_Y_TOP_CTRL = 0.62      # ROI 비율 (아래쪽 38%만 사용) → 제어용
        self.ROI_Y_TOP_CLASS = 0.35     # ROI 비율 (아래쪽 65%만 사용) → 차선 종류 판별용
        self.CANNY_T1, self.CANNY_T2 = 60, 150  # Canny 엣지 검출 임계값
        self.HOUGH_TH = 30              # 허프라인 최소 누적값
        self.HOUGH_MINLEN = 20          # 최소 선분 길이
        self.HOUGH_MAXGAP = 8           # 선분 사이 허용 gap
        
        # --- 차선 종류(실선/점선) 판별 파라미터 ---
        self.STRIP_WIDTH = 16           # 차선 스트립 샘플링 폭
        self.COV_SOLID_THRESH = 0.78    # 커버리지(coverage) 임계값 (실선 판정 기준)
        self.MAX_GAP_SOLID_THRESH = 18  # 실선일 때 허용되는 최대 gap 픽셀 길이
        self.MIN_GAPS_DASHED = 2        # 점선으로 분류하기 위한 최소 단절 개수
        self.LONG_GAP_PIX = 20          # 긴 gap 픽셀 수 기준
        self.SMOOTH_WIN = 9             # 스무딩 커널 크기
        
        # --- 스무딩 변수 ---
        self.lane_center_ema = None     # 차선 중심 (EMA, 지수이동평균)
        self.ALPHA_CENTER = 0.30        # 중심 EMA 계수
        self.prev_Lk_vis = None         # 이전 프레임 왼쪽 차선 (시각화용)
        self.prev_Rk_vis = None         # 이전 프레임 오른쪽 차선 (시각화용)
        self.ALPHA_VIS = 0.20           # 시각화용 EMA 계수


    # ROI(관심영역) 적용 (위쪽 잘라내기)
    def _apply_roi_top(self, gray_img, y_top_ratio):
        h, w = gray_img.shape[:2]
        y_top = int(h * y_top_ratio)  # 기준 y 좌표
        roi = gray_img.copy()
        roi[:y_top, :] = 0           # 위쪽 영역을 0으로 마스킹
        return roi

    # 허프라인 결과를 왼쪽/오른쪽 그룹으로 분리
    def _split_left_right(self, lines, center_x):
        left, right = [], []
        if lines is None: return left, right
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            slope = 1e9 if x2 == x1 else (y2 - y1) / (x2 - x1)  # 기울기
            if abs(slope) < 0.3: continue  # 수평선 제외
            mx = (x1 + x2) / 2
            (left if mx < center_x else right).append((x1, y1, x2, y2))
        return left, right
    
    # 여러 선분 평균 → 대표 차선 1개 생성
    def _average_line(self, lines, h, roi_top_ratio):
        if not lines: return None
        xs, ys, xe, ye = map(np.array, zip(*lines))
        x1, y1, x2, y2 = int(xs.mean()), int(ys.mean()), int(xe.mean()), int(ye.mean())
        if x2 == x1: x2 += 1
        slope = (y2 - y1) / (x2 - x1)
        b = y1 - slope * x1

        # ROI 범위에 맞춰 선분 좌표 확장
        y_bottom = h - 1
        y_top = int(h * roi_top_ratio)
        x_bottom = int((y_bottom - b) / slope); x_top = int((y_top - b) / slope)
        return (x_bottom, y_bottom, x_top, y_top)
    

    # 좌/우 차선 중심으로 도로 중앙 좌표 계산
    def _lane_center_from_lines(self, l_line, r_line, h):
        y_eval = int(h * 0.9)
        xs = []
        for L in (l_line, r_line):
            if L is None: continue
            xb, yb, xt, yt = L
            if xt == xb: xs.append(xb); continue
            m = (yt - yb) / (xt - xb)
            if abs(m) < 1e-6: continue
            b = yb - m * xb
            xs.append(int((y_eval - b) / m))
        if len(xs) == 2: return int((xs[0] + xs[1]) // 2) # 양쪽 평균
        elif len(xs) == 1: return xs[0]  # 하나만 있으면 그 좌표
        else: return None

    # --- 차선 종류 분류 헬퍼 함수들 ---
    def _extract_rotated_strip(self, src_img, x1,y1,x2,y2):
        length = int(math.hypot(x2-x1, y2-y1)) # 선 길이
        if length < 20: return None
        cx, cy = (x1 + x2) * 0.5, (y1 + y2) * 0.5 # 중심점 
        angle_deg = math.degrees(math.atan2(y2 - y1, x2 - x1)) # 기울기
        M = cv2.getRotationMatrix2D((cx, cy), angle_deg, 1.0) # 회전 행렬
        h, w = src_img.shape[:2]
        rot = cv2.warpAffine(src_img, M, (w, h), flags=cv2.INTER_NEAREST)

        # 선 중심을 기준으로 스트립 자르기
        x_start, x_end = int(cx - length/2), int(cx + length/2)
        y1s, y2s = int(cy - self.STRIP_WIDTH/2), int(cy + self.STRIP_WIDTH/2)
        x_start, y1s = max(0, x_start), max(0, y1s)
        x_end, y2s = min(w, x_end), min(h, y2s)
        if x_end - x_start < 10 or y2s - y1s < 1: return None
        return rot[y1s:y2s, x_start:x_end]
    
    # 이진 스트립의 연속 구간(run-length) 정보 추출
    def _runs_info(self, binary_1d):
        vals = binary_1d.astype(np.uint8)
        if vals.size == 0: return [], 0, 0
        runs = []; cur_v, cur_len = vals[0], 1
        for v in vals[1:]:
            if v == cur_v: cur_len += 1
            else: runs.append((cur_v, cur_len)); cur_v, cur_len = v, 1
        runs.append((cur_v, cur_len))
        max_zero = max((l for v,l in runs if v==0), default=0)
        zero_cnt = sum(1 for v,l in runs if v==0 and l >= self.LONG_GAP_PIX)
        return runs, max_zero, zero_cnt
    
    # 차선 실선/점선 판별
    def _classify_line_type(self, mask_img, line):
        if line is None: return None
        x1,y1,x2,y2 = line
        strip = self._extract_rotated_strip(mask_img, x1,y1,x2,y2)
        if strip is None: return None
        col_mean = strip.mean(axis=0) # 세로 방향 평균

        # 스무딩 (moving average)
        k = max(1, self.SMOOTH_WIN)
        kernel = np.ones(k, dtype=np.float32) / k
        smooth = np.convolve(col_mean, kernel, mode='same')

        # thresholding
        thr = 0.3 * smooth.max()
        binary = (smooth > thr).astype(np.uint8)
        coverage = binary.mean()
        _, max_zero_run, long_zero_cnt = self._runs_info(binary)

        # 조건에 따라 실선/점선 판별
        if coverage >= self.COV_SOLID_THRESH and max_zero_run <= self.MAX_GAP_SOLID_THRESH: return "solid"
        if long_zero_cnt >= self.MIN_GAPS_DASHED and coverage < 0.85: return "dashed"
        return "solid" if coverage > 0.72 else "dashed"


    # 현재 차선 번호 추정 (1,2,3차로)
    def _determine_current_lane(self, left_type, right_type):
        if left_type == "solid"  and right_type == "dashed": return 1
        if left_type == "dashed" and right_type == "dashed": return 2
        if left_type == "dashed" and right_type == "solid":  return 3
        return None
    
    # 중심 좌표 지수이동평균 스무딩
    def _smooth_center_ema(self, center):
        if center is None: return self.lane_center_ema
        if self.lane_center_ema is None: self.lane_center_ema = center
        else: self.lane_center_ema = int(self.ALPHA_CENTER * center + (1 - self.ALPHA_CENTER) * self.lane_center_ema)
        return self.lane_center_ema

    # 선분 스무딩 (시각화 안정화용)
    def _safe_ema_line(self, prev, new, alpha):
        if new is None: return prev
        if prev is None: return new
        return tuple(int((1-alpha)*p + alpha*n) for p, n in zip(prev, new))
    
    # 프레임 처리: 차선 검출 + 시각화
    def process_frame(self, frame):
        h, w = frame.shape[:2]; cx = w // 2

        # 흰색 차선 추출 (HSV 마스크)
        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
        lower_white = np.array([0, 0, 200], dtype=np.uint8)
        upper_white = np.array([180, 40, 255], dtype=np.uint8)
        mask = cv2.inRange(hsv, lower_white, upper_white)
        mask = cv2.GaussianBlur(mask, (5, 5), 0)


        # 제어용 ROI → 허프라인 → 차선 후보
        roi_ctrl = self._apply_roi_top(mask, self.ROI_Y_TOP_CTRL)
        edges_ctrl = cv2.Canny(roi_ctrl, self.CANNY_T1, self.CANNY_T2)
        lines_ctrl = cv2.HoughLinesP(edges_ctrl, 1, np.pi/180, self.HOUGH_TH, minLineLength=self.HOUGH_MINLEN, maxLineGap=self.HOUGH_MAXGAP)
        left_c, right_c = self._split_left_right(lines_ctrl, cx)
        Lc = self._average_line(left_c, h, self.ROI_Y_TOP_CTRL)
        Rc = self._average_line(right_c, h, self.ROI_Y_TOP_CTRL)

        # 차선 종류 판별용 ROI
        roi_cls = self._apply_roi_top(mask, self.ROI_Y_TOP_CLASS)
        lines_cls = cv2.HoughLinesP(cv2.Canny(roi_cls, self.CANNY_T1, self.CANNY_T2), 1, np.pi/180, self.HOUGH_TH, minLineLength=self.HOUGH_MINLEN, maxLineGap=self.HOUGH_MAXGAP)
        left_k, right_k = self._split_left_right(lines_cls, cx)
        Lk_raw = self._average_line(left_k, h, self.ROI_Y_TOP_CLASS)
        Rk_raw = self._average_line(right_k, h, self.ROI_Y_TOP_CLASS)

        # 실선/점선 분류
        left_type = self._classify_line_type(roi_cls, Lk_raw)
        right_type = self._classify_line_type(roi_cls, Rk_raw)
        current_lane = self._determine_current_lane(left_type, right_type)


        # EMA 적용 (시각화 안정화)
        self.prev_Lk_vis = self._safe_ema_line(self.prev_Lk_vis, Lk_raw, self.ALPHA_VIS)
        self.prev_Rk_vis = self._safe_ema_line(self.prev_Rk_vis, Rk_raw, self.ALPHA_VIS)
        Lk_vis, Rk_vis = self.prev_Lk_vis, self.prev_Rk_vis
        
        # 차선 중앙 계산 + EMA
        lane_cx_raw = self._lane_center_from_lines(Lc, Rc, h)
        lane_cx_s = self._smooth_center_ema(lane_cx_raw)
        
        # --- 시각화 ---
        vis_frame = frame.copy()
        if Lc: cv2.line(vis_frame, (Lc[0], Lc[1]), (Lc[2], Lc[3]), (0, 255, 0), 3)
        if Rc: cv2.line(vis_frame, (Rc[0], Rc[1]), (Rc[2], Rc[3]), (0, 255, 0), 3)
        if Lk_vis: cv2.line(vis_frame, (Lk_vis[0], Lk_vis[1]), (Lk_vis[2], Lk_vis[3]), (0, 255, 255), 2)
        if Rk_vis: cv2.line(vis_frame, (Rk_vis[0], Rk_vis[1]), (Rk_vis[2], Rk_vis[3]), (0, 255, 255), 2)
        if lane_cx_s:
            cv2.line(vis_frame, (lane_cx_s, int(h*0.8)), (lane_cx_s, h), (255, 255, 0), 2)
        else:
            cv2.putText(vis_frame, "LANE NOT DETECTED", (50,50), cv2.FONT_HERSHEY_SIMPLEX,1.0,(0,0,255),2)
        
        # 반환 결과
        return {
            "vis_frame": vis_frame,              # 시각화용 프레임
            "lane_center_raw": lane_cx_raw,      # 차선 중심 (raw)
            "lane_center_smooth": lane_cx_s,     # 차선 중심 (EMA 적용)
            "left_line_ctrl": Lc,                # 왼쪽 제어용 차선
            "right_line_ctrl": Rc,               # 오른쪽 제어용 차선
            "current_lane": current_lane,        # 현재 차로 번호 (1~3)
        }
