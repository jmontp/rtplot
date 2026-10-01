"""Verify the repository Windows build matches its archived committed source.

Run with .build/windows/venv/Scripts/python.exe after build-windows.ps1.
No listener or hardware connection is opened.
"""
from pathlib import Path
import hashlib,json,os,subprocess
from PyInstaller.archive.readers import CArchiveReader
root=Path(__file__).resolve().parents[1]
build=root/'.build'/'windows'
exe=root/'dist'/'rtplot-server.exe'
archive=CArchiveReader(str(exe))
pyz=archive.open_embedded_archive(next(k for k in archive.toc if k.endswith('.pyz')))
results={}
for module in ('rtplot.client','rtplot.server_browser','rtplot.ui_state','rtplot.xy'):
 actual=pyz.extract(module)
 source=build/'source'/Path(*module.split('.')).with_suffix('.py')
 expected=compile(source.read_bytes(),actual.co_filename,'exec',dont_inherit=True,optimize=0)
 results[module]=actual==expected
 if not results[module]: raise RuntimeError('Packaged module differs: '+module)
assets={}
for relative in ('rtplot/static/index.html','rtplot/static/ui-view.js','rtplot/static/presentation.css','rtplot/static/uPlot.iife.min.js','rtplot/static/uPlot.min.css'):
 key=next(k for k in archive.toc if k.replace('\\','/')==relative)
 actual=archive.extract(key)
 expected=(build/'source'/relative).read_bytes()
 if actual != expected: raise RuntimeError('Packaged asset differs: '+relative)
 assets[relative]=hashlib.sha256(actual).hexdigest()
(build/'temp').mkdir(exist_ok=True)
env=os.environ.copy();env['TEMP']=str(build/'temp');env['TMP']=env['TEMP']
smoke=subprocess.run([str(exe),'--no-gui','--help'],capture_output=True,text=True,timeout=45,env=env)
if smoke.returncode: raise RuntimeError('Executable help failed: '+repr(smoke))
result={'exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'exe_bytes':exe.stat().st_size,'modules_equal_clean_source':results,'packaged_assets_sha256':assets,'help_exit_code':smoke.returncode,'help_stdout':smoke.stdout,'help_stderr':smoke.stderr,'live_server_started':False}
(root/'dist'/'build-verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
