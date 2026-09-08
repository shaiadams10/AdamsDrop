import asyncio,io,time,win32clipboard

import json

from pathlib import Path

import ipad_transport

ipad_transport.install()

from PIL import Image

from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel

from pymobiledevice3.remote.core_device.pasteboard_service import PasteboardService,snapshot_text

async def main():

 device=json.loads((Path(__file__).parent/'config.json').read_text())['direct_device']

 async with UserspaceRsdTunnel(serial=device,autopair=False) as rsd:

  for kind in ['image','text']:

   im=Image.new('RGB',(1280,720),(30,130,180));b=io.BytesIO();im.save(b,format='BMP')

   sample='AdamsDrop automatic clipboard verified'

   t=time.perf_counter();win32clipboard.OpenClipboard()

   try:

    win32clipboard.EmptyClipboard()

    win32clipboard.SetClipboardData(win32clipboard.CF_DIB,b.getvalue()[14:]) if kind=='image' else win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT,sample)

   finally:win32clipboard.CloseClipboard()

   match=False

   for _ in range(60):

    await asyncio.sleep(.1)

    async with PasteboardService(rsd) as p:r=await p.get()

    if kind=='text':match=snapshot_text(r)==sample

    else:

     for item in r.get('pasteboard',r).get('items',[]):

      raw=item.get('data',{}).get('public.png',{}).get('data')

      if raw:

       got=Image.open(io.BytesIO(raw));match=got.size==im.size and got.convert('RGB').tobytes()==im.tobytes()

    if match:break

   print(kind,'automatic match:',match,'observed ms:',round((time.perf_counter()-t)*1000,1),flush=True)

   assert match

asyncio.run(main())
