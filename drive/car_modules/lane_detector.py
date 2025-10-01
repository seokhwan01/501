import cv2
import numpy as np
import math

class LaneDetector:
    def __init__(self):
        # --- 직선 주행에 최적화된 튜닝 파라미터 ---
        self.ROI_Y_TOP_CTRL = 0.62
        self.ROI_Y_TOP_CLASS = 0.35
        self.CANNY_T1, self.CANNY_T2 = 60, 150
        self.HOUGH_TH, self.HOUGH_MINLEN, self.HOUGH_MAXGAP = 30, 20, 8
        
        # --- 차선 종류 판별 파라미터 (원래의 정교한 값) ---
        self.STRIP_WIDTH = 16
        self.COV_SOLID_THRESH = 0.78
        self.MAX_GAP_SOLID_THRESH = 18
        self.MIN_GAPS_DASHED = 2
        self.LONG_GAP_PIX = 20
        self.SMOOTH_WIN = 9
        
        # --- 스무딩 변수 ---
        self.lane_center_ema = None
        self.ALPHA_CENTER = 0.30
        self.prev_Lk_vis = None
        self.prev_Rk_vis = None
        self.ALPHA_VIS = 0.20

    def _apply_roi_top(self, gray_img, y_top_ratio):
        h, w = gray_img.shape[:2]
        y_top = int(h * y_top_ratio)
        roi = gray_img.copy()
        roi[:y_top, :] = 0
        return roi

    def _split_left_right(self, lines, center_x):
        left, right = [], []
        if lines is None: return left, right
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            slope = 1e9 if x2 == x1 else (y2 - y1) / (x2 - x1)
            if abs(slope) < 0.3: continue
            mx = (x1 + x2) / 2
            (left if mx < center_x else right).append((x1, y1, x2, y2))
        return left, right

    def _average_line(self, lines, h, roi_top_ratio):
        if not lines: return None
        xs, ys, xe, ye = map(np.array, zip(*lines))
        x1, y1, x2, y2 = int(xs.mean()), int(ys.mean()), int(xe.mean()), int(ye.mean())
        if x2 == x1: x2 += 1
        slope = (y2 - y1) / (x2 - x1)
        b = y1 - slope * x1
        y_bottom = h - 1
        y_top = int(h * roi_top_ratio)
        x_bottom = int((y_bottom - b) / slope); x_top = int((y_top - b) / slope)
        return (x_bottom, y_bottom, x_top, y_top)

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
        if len(xs) == 2: return int((xs[0] + xs[1]) // 2)
        elif len(xs) == 1: return xs[0]
        else: return None

    # --- 차선 종류 분류 헬퍼 함수들 ---
    def _extract_rotated_strip(self, src_img, x1,y1,x2,y2):
        length = int(math.hypot(x2-x1, y2-y1))
        if length < 20: return None
        cx, cy = (x1 + x2) * 0.5, (y1 + y2) * 0.5
        angle_deg = math.degrees(math.atan2(y2 - y1, x2 - x1))
        M = cv2.getRotationMatrix2D((cx, cy), angle_deg, 1.0)
        h, w = src_img.shape[:2]
        rot = cv2.warpAffine(src_img, M, (w, h), flags=cv2.INTER_NEAREST)
        x_start, x_end = int(cx - length/2), int(cx + length/2)
        y1s, y2s = int(cy - self.STRIP_WIDTH/2), int(cy + self.STRIP_WIDTH/2)
        x_start, y1s = max(0, x_start), max(0, y1s)
        x_end, y2s = min(w, x_end), min(h, y2s)
        if x_end - x_start < 10 or y2s - y1s < 1: return None
        return rot[y1s:y2s, x_start:x_end]

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

    def _classify_line_type(self, mask_img, line):
        if line is None: return None
        x1,y1,x2,y2 = line
        strip = self._extract_rotated_strip(mask_img, x1,y1,x2,y2)
        if strip is None: return None
        col_mean = strip.mean(axis=0)
        k = max(1, self.SMOOTH_WIN)
        kernel = np.ones(k, dtype=np.float32) / k
        smooth = np.convolve(col_mean, kernel, mode='same')
        thr = 0.3 * smooth.max()
        binary = (smooth > thr).astype(np.uint8)
        coverage = binary.mean()
        _, max_zero_run, long_zero_cnt = self._runs_info(binary)
        if coverage >= self.COV_SOLID_THRESH and max_zero_run <= self.MAX_GAP_SOLID_THRESH: return "solid"
        if long_zero_cnt >= self.MIN_GAPS_DASHED and coverage < 0.85: return "dashed"
        return "solid" if coverage > 0.72 else "dashed"

    def _determine_current_lane(self, left_type, right_type):
        if left_type == "solid"  and right_type == "dashed": return 1
        if left_type == "dashed" and right_type == "dashed": return 2
        if left_type == "dashed" and right_type == "solid":  return 3
        return None

    def _smooth_center_ema(self, center):
        if center is None: return self.lane_center_ema
        if self.lane_center_ema is None: self.lane_center_ema = center
        else: self.lane_center_ema = int(self.ALPHA_CENTER * center + (1 - self.ALPHA_CENTER) * self.lane_center_ema)
        return self.lane_center_ema

    def _safe_ema_line(self, prev, new, alpha):
        if new is None: return prev
        if prev is None: return new
        return tuple(int((1-alpha)*p + alpha*n) for p, n in zip(prev, new))

    def process_frame(self, frame):
        h, w = frame.shape[:2]; cx = w // 2

        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
        lower_white = np.array([0, 0, 200], dtype=np.uint8)
        upper_white = np.array([180, 40, 255], dtype=np.uint8)
        mask = cv2.inRange(hsv, lower_white, upper_white)
        mask = cv2.GaussianBlur(mask, (5, 5), 0)

        roi_ctrl = self._apply_roi_top(mask, self.ROI_Y_TOP_CTRL)
        edges_ctrl = cv2.Canny(roi_ctrl, self.CANNY_T1, self.CANNY_T2)
        lines_ctrl = cv2.HoughLinesP(edges_ctrl, 1, np.pi/180, self.HOUGH_TH, minLineLength=self.HOUGH_MINLEN, maxLineGap=self.HOUGH_MAXGAP)
        left_c, right_c = self._split_left_right(lines_ctrl, cx)
        Lc = self._average_line(left_c, h, self.ROI_Y_TOP_CTRL)
        Rc = self._average_line(right_c, h, self.ROI_Y_TOP_CTRL)

        roi_cls = self._apply_roi_top(mask, self.ROI_Y_TOP_CLASS)
        lines_cls = cv2.HoughLinesP(cv2.Canny(roi_cls, self.CANNY_T1, self.CANNY_T2), 1, np.pi/180, self.HOUGH_TH, minLineLength=self.HOUGH_MINLEN, maxLineGap=self.HOUGH_MAXGAP)
        left_k, right_k = self._split_left_right(lines_cls, cx)
        Lk_raw = self._average_line(left_k, h, self.ROI_Y_TOP_CLASS)
        Rk_raw = self._average_line(right_k, h, self.ROI_Y_TOP_CLASS)

        left_type = self._classify_line_type(roi_cls, Lk_raw)
        right_type = self._classify_line_type(roi_cls, Rk_raw)
        current_lane = self._determine_current_lane(left_type, right_type)

        self.prev_Lk_vis = self._safe_ema_line(self.prev_Lk_vis, Lk_raw, self.ALPHA_VIS)
        self.prev_Rk_vis = self._safe_ema_line(self.prev_Rk_vis, Rk_raw, self.ALPHA_VIS)
        Lk_vis, Rk_vis = self.prev_Lk_vis, self.prev_Rk_vis
        
        lane_cx_raw = self._lane_center_from_lines(Lc, Rc, h)
        lane_cx_s = self._smooth_center_ema(lane_cx_raw)
        
        vis_frame = frame.copy()
        if Lc: cv2.line(vis_frame, (Lc[0], Lc[1]), (Lc[2], Lc[3]), (0, 255, 0), 3)
        if Rc: cv2.line(vis_frame, (Rc[0], Rc[1]), (Rc[2], Rc[3]), (0, 255, 0), 3)
        if Lk_vis: cv2.line(vis_frame, (Lk_vis[0], Lk_vis[1]), (Lk_vis[2], Lk_vis[3]), (0, 255, 255), 2)
        if Rk_vis: cv2.line(vis_frame, (Rk_vis[0], Rk_vis[1]), (Rk_vis[2], Rk_vis[3]), (0, 255, 255), 2)
        if lane_cx_s:
            cv2.line(vis_frame, (lane_cx_s, int(h*0.8)), (lane_cx_s, h), (255, 255, 0), 2)
        else:
            cv2.putText(vis_frame, "LANE NOT DETECTED", (50,50), cv2.FONT_HERSHEY_SIMPLEX,1.0,(0,0,255),2)
        
        return {
            "vis_frame": vis_frame,
            "lane_center_raw": lane_cx_raw,
            "lane_center_smooth": lane_cx_s,
            "left_line_ctrl": Lc,
            "right_line_ctrl": Rc,
            "current_lane": current_lane,
        }

