"""User-requested additional backoff for an already-running frozen Windows worker.
No API calls, no worker edits, no restart. Suspends only the pinned process after
new logged429s for Retry-After+3 seconds; earlier responses remain historical.
"""
import ctypes
from ctypes import wintypes
import hashlib,json,os,time
from datetime import datetime,timezone
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
ROOT=BASE/'runs/goedel_seed2_backoff_20261109'
LOG=ROOT.parent/'goedel_backoff_buffer_20261109'
LOG.mkdir(exist_ok=True)
worker=json.loads((ROOT/'execution.json').read_text())
path=next((ROOT/'market').iterdir())/'llm_requests.jsonl'
k=ctypes.WinDLL('kernel32',use_last_error=True)
n=ctypes.WinDLL('ntdll')
k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE
k.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];k.WaitForSingleObject.restype=wintypes.DWORD
k.CloseHandle.argtypes=[wintypes.HANDLE]
n.NtSuspendProcess.argtypes=[wintypes.HANDLE];n.NtSuspendProcess.restype=ctypes.c_long
n.NtResumeProcess.argtypes=[wintypes.HANDLE];n.NtResumeProcess.restype=ctypes.c_long
handle=k.OpenProcess(0x100000|0x0800|0x1000,False,worker['pid'])
if not handle:raise ctypes.WinError(ctypes.get_last_error())
def log(record):
 record['utc']=datetime.now(timezone.utc).isoformat()
 with (LOG/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record)+'\n')
try:
 with (LOG/'execution.json').open('x',encoding='utf-8') as f:
  json.dump(dict(pid=os.getpid(),worker_pid=worker['pid'],worker_started_utc=worker['started_utc'],source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),policy='For new429events,hold pinned worker for parsed Retry-After+3seconds after detection. No new requests or restart.'),f,indent=2)
 with path.open('r',encoding='utf-8') as f:
  f.seek(0,2);pending='';log(dict(event='monitor_started',offset=f.tell()))
  while k.WaitForSingleObject(handle,0)==258:
   chunk=f.read()
   if not chunk:time.sleep(.05);continue
   pending+=chunk
   while '\n' in pending:
    line,pending=pending.split('\n',1)
    if not line.strip():continue
    x=json.loads(line)
    if x.get('http_status')!=429 or not x.get('transport_retry_planned'):continue
    delay=x.get('retry_after',{}).get('retry_after_seconds')
    wait=(delay if isinstance(delay,(int,float)) and delay>=0 else x['retry_wait_seconds']-1)+3
    if n.NtSuspendProcess(handle)!=0:raise RuntimeError('Worker suspension failed')
    start=time.monotonic()
    try:
     log(dict(event='backoff_hold_started',call_id=x['call_id'],retry_after_seconds=delay,hold_seconds=wait))
     time.sleep(wait)
    finally:
     status=n.NtResumeProcess(handle)
     log(dict(event='backoff_hold_finished',call_id=x['call_id'],elapsed_seconds=time.monotonic()-start,resume_status=status))
     if status!=0:raise RuntimeError('Worker resume failed')
 log(dict(event='worker_exited'))
finally:k.CloseHandle(handle)
