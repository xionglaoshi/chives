"""Install the current user's macOS launch agent; also check overdue work on login/wake."""
import argparse
import os
import plistlib
import subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser()
parser.add_argument('--data', type=Path, required=True, help='production workspace outside the Chives installation')
output=parser.parse_args().data.resolve()
if output.is_relative_to(root) or output.is_relative_to(Path.home()/'.chives'):
    parser.error('--data 必须指向 Chives 安装根之外的生产工作区')
output.mkdir(parents=True,exist_ok=True)
label='local.chives.hotspots'
domain=f'gui/{os.getuid()}'
target=Path.home()/'Library/LaunchAgents'/(label+'.plist')
target.parent.mkdir(parents=True,exist_ok=True)
spec=dict(Label=label,ProgramArguments=[str(root/'.venv/bin/python'),str(root/'scripts/hotspots/generate.py'),'--due','--data',str(output)],
          RunAtLoad=True,StartCalendarInterval=dict(Hour=8,Minute=30),StartInterval=900,
          WorkingDirectory=str(output),ProcessType='Background',
          EnvironmentVariables={'TMPDIR':str(root/'runtime/tmp')+'/', 'PATH':str(Path.home()/'.local/bin')+':/opt/homebrew/bin:/usr/bin:/bin','TZ':'Asia/Shanghai'},
          StandardOutPath=str(output/'generate.log'),StandardErrorPath=str(output/'generate.log'))
tmp=target.with_suffix('.tmp');tmp.write_bytes(plistlib.dumps(spec));os.replace(tmp,target)
subprocess.run(['launchctl','bootout',domain+'/'+label],capture_output=True)
subprocess.run(['launchctl','bootstrap',domain,str(target)],check=True)
