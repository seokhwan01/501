import threading
import hashlib
from pathlib import Path
import subprocess
import shutil
from gtts import gTTS

# --- 설정 ---
TTS_CACHE_DIR = Path("/tmp/tts_cache")
TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_tts_lock = threading.Lock()

def _have_cmd(cmd: str) -> bool:
    """시스템에 특정 명령어가 있는지 확인합니다."""
    return shutil.which(cmd) is not None

def _synthesize_to_cache(text: str) -> Path:
    """gTTS를 사용하여 텍스트를 mp3 파일로 합성하고 캐시에 저장합니다."""
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    audio_path = TTS_CACHE_DIR / f"{h}.mp3"

    if audio_path.exists():
        print(f"[gTTS] 캐시된 오디오 사용: {audio_path}")
        return audio_path

    print("[gTTS] Google TTS API로 오디오 생성 중...")
    try:
        tts = gTTS(text=text, lang='ko', tld='co.kr', timeout=5)
        tts.save(str(audio_path))
        print(f"[gTTS] 오디오 파일 저장 성공: {audio_path}")
        return audio_path
    except Exception as e:
        print("="*50)
        print(f"[gTTS] !!! 오디오 생성 실패 !!!")
        print(f"오류 종류: {type(e).__name__}")
        print(f"오류 내용: {e}")
        print("인터넷 연결 또는 방화벽 설정을 확인해주세요.")
        print("="*50)
        return None

def _play_audio(path: Path):
    """mp3 또는 wav 파일을 재생합니다."""
    if not path or not path.exists():
        print("[Player] 재생할 오디오 파일이 없습니다.")
        return

    player_cmd = None
    if path.suffix == '.mp3' and _have_cmd("mpg123"):
        player_cmd = ["mpg123", "-q", str(path)]
    elif _have_cmd("aplay"): # wav 파일용 fallback
        player_cmd = ["aplay", "-q", str(path)]
    elif _have_cmd("ffplay"):
        player_cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", str(path)]
    else:
        print("[Player] 오디오 재생기(mpg123, aplay, ffplay)가 설치되어 있지 않습니다.")
        return
    
    try:
        print(f"[Player] {player_cmd[0]}으로 재생 시작...")
        subprocess.run(player_cmd, timeout=30)
    except Exception as e:
        print(f"[Player] 오디오 재생 실패: {e}")

def _speak_thread(text: str):
    """별도 스레드에서 음성을 합성하고 재생합니다."""
    if not _tts_lock.acquire(blocking=False):
        print("[TTS] 다른 음성 출력이 진행 중입니다. 이번 요청은 건너뜁니다.")
        return
    try:
        print(f"[TTS] 음성 출력 요청: {text}")
        
        audio_path = _synthesize_to_cache(text)
        
        if audio_path:
            _play_audio(audio_path)
            return

        print("[TTS] gTTS 실패. 예비方案(espeak-ng)을 시도합니다.")
        if _have_cmd("espeak-ng"):
            try:
                fallback_path = TTS_CACHE_DIR / "fallback_temp.wav"
                subprocess.run(
                    ["espeak-ng", "-v", "ko", "-w", str(fallback_path), text],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
                )
                print(f"[TTS] espeak-ng 합성 성공: {fallback_path}")
                _play_audio(fallback_path)
            except Exception as ee:
                print(f"[TTS] espeak-ng 마저 실패했습니다: {ee}")
        else:
            print("[TTS] 예비方案(espeak-ng)도 설치되어 있지 않습니다.")

    finally:
        _tts_lock.release()

def announce_evasion(direction: str, minutes: int):
    """긴급 회피 안내 방송을 시작합니다."""
    text = f"긴급 차량이 {minutes}분 후 도착합니다. {direction}으로 비켜 주세요."
    # [수정됨] 괄호가 닫히지 않은 문법 오류 수정 및 스레드 시작
    thread = threading.Thread(target=_speak_thread, args=(text,), daemon=True)
    thread.start()

