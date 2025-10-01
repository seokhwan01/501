// ---- 상태 업데이트 ----
async function updateStatus(){
  try{
    const s = await (await fetch('/api/status')).json();
    
    document.getElementById('lane_info').textContent = s.lane_text ?? '?';
    document.getElementById('lane_total_info').textContent = s.lane_total ?? '3';
    document.getElementById('speed_info').textContent = s.speed_text ?? '0.00';
    document.getElementById('state_info').textContent = s.state_text ?? '-';
    document.getElementById('steering_angle_info').textContent = s.steering_angle.toFixed(1);
    
    const btnStop = document.getElementById('btnStop');
    if (s.state_text && (s.state_text.toUpperCase().includes('STOP'))) {
      btnStop.textContent = 'RESUME';
      btnStop.classList.remove('btn-stop'); btnStop.classList.add('btn-resume');
    } else {
      btnStop.textContent = 'STOP';
      btnStop.classList.remove('btn-resume'); btnStop.classList.add('btn-stop');
    }
  }catch(e){ console.error("Update failed:", e); }
}
setInterval(updateStatus, 500);
updateStatus();

// ---- 제어 요청 ----
function sendControl(action){
  return fetch('/api/control', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({action})
  });
}

document.getElementById('btnBackward').onclick = () => sendControl("toggle_backward");
document.getElementById('btnStop').onclick = () => sendControl("toggle_stop").then(updateStatus);

window.addEventListener('keydown', async (e)=>{
  if(e.key==='q'||e.key==='Q'){ await sendControl("quit"); }
  else if(e.key==='ArrowRight'){ await sendControl("turn_right"); }
  else if(e.key==='ArrowLeft'){ await sendControl("turn_left"); }
  else if(e.key==='ArrowUp'){ await sendControl("speed_up"); }
  else if(e.key==='ArrowDown'){ await sendControl("speed_down"); }
  else if(e.key===' '){ e.preventDefault(); await sendControl("toggle_stop"); }
  else if(e.key==='b'||e.key==='B'){ await sendControl("toggle_backward"); }
});
window.addEventListener('keyup', async (e)=>{
  if(e.key==='ArrowRight'||e.key==='ArrowLeft'){ await sendControl("turn_stop"); }
});

// ---- WebSocket 영상 수신 ----
const socket = io();
socket.on("video_frame", data => {
  document.getElementById("video").src = "data:image/jpeg;base64," + data.img;
});
