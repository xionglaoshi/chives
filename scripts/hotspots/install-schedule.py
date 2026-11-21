"""Install the current user's macOS launch agent; also check overdue work on login/wake."""
import os
import plistlib
import subprocess
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
label='local.chives.hotspots'
domain=f'gui/{os.getuid()}'
target=Path.home()/'Library/LaunchAgents'/(label+'.plist')
target.parent.mkdir(parents=True,exist_ok=True)
spec=dict(Label=label,ProgramArguments=[sys.executable,str(root/'scripts/hotspots/generate.py'),'--due','--data',str(root/'data/hotspots')],
          RunAtLoad=True,StartCalendarInterval=dict(Hour=8,Minute=30),StartInterval=900,
          WorkingDirectory=str(root),ProcessType='Background',
          EnvironmentVariables={'TMPDIR':str(root/'runtime/tmp')+'/', 'PATH':str(Path.home()/'.local/bin')+':/opt/homebrew/bin:/usr/bin:/bin','TZ':'Asia/Shanghai'},
          StandardOutPath=str(root/'runtime/hotspots.log'),StandardErrorPath=str(root/'runtime/hotspots.log'))
tmp=target.with_suffix('.tmp');tmp.write_bytes(plistlib.dumps(spec));os.replace(tmp,target)
subprocess.run(['launchctl','bootout',domain+'/'+label],capture_output=True)
subprocess.run(['launchctl','bootstrap',domain,str(target)],check=True)
