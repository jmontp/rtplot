"""Checkbox source fixture: requests only change state after explicit confirmation."""
import json
import queue
import sys
import threading
import time
from rtplot import client
commands=queue.Queue()
def read():
    for line in sys.stdin:
        commands.put(json.loads(line))
threading.Thread(target=read,daemon=True).start()
client.local_plot()
client.initialize_plots([dict(names=['signal'],controls=[client.Checkbox('filter','Trained filter').to_dict()])],
    ui_state={'controls':{'filter':{'selected':False}}})
print(json.dumps({'ready':True}),flush=True)
requests=[]
while True:
    state=client.poll_controls()
    requests.extend(state.buttons)
    while not commands.empty():
        c=commands.get()
        if c['op']=='state': result=requests
        elif c['op']=='patch': result=client.set_ui_state(c['patch'])
        else: result=None
        print(json.dumps({'command':c['serial'],'result':result}),flush=True)
    client.send_array([0.])
    time.sleep(.01)
