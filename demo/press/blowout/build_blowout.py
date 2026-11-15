import base64
F="/Users/aarya/dev_all/gia-mobile/mobile/node_modules/@expo-google-fonts/inter/"
css=""
for w,p in [(400,"400Regular/Inter_400Regular.ttf"),(600,"600SemiBold/Inter_600SemiBold.ttf")]:
    b=base64.b64encode(open(F+p,'rb').read()).decode()
    css+='@font-face{font-family:"Inter";font-weight:%d;font-style:normal;src:url(data:font/ttf;base64,%s) format("truetype");}\n'%(w,b)
s=open("/tmp/blowout_tpl.html").read()
s=s.replace("/*FONTS*/",css).replace("<!--TABLET-->",open("/tmp/tablet_block.svg").read())
open("/Users/aarya/dev_all/hack-princton/firstin/demo/press/blowout/blowout.html","w").write(s)
