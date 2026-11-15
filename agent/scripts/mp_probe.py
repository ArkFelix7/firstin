import json,sys
from agent.scripts.mp_gql import gql
q='''query($id:ID!){ model(id:$id){ id name floors { id label sequence dimensions(units:imperial){areaFloor} } 
rooms { id label tags keywords floor { id label sequence } classifications { label confidence } dimensions(units:imperial){ areaFloor width depth height } }
mattertags { id label description floor { sequence } anchorPosition { x y z } }
locations { id label floor { sequence } position { x y z } room { id label } panos { id variant label } }
assets { floorplans { id url format flags floor { sequence } width height } photos { id label url name type } }
image { url } geolocation { lat long } dimensions(units:imperial){ areaFloor } } }'''
d=gql(q,{"id":sys.argv[1]})
if d.get('errors'): print(json.dumps(d.get('errors'))[:2000])
md=d['data']['model']
print(md['name'],'floors',md['floors']);print('rooms',len(md['rooms']))
for r in md['rooms'][:25]: print(' ',r.get('label'),r.get('tags'),r.get('keywords'),[c.get('label') for c in (r.get('classifications') or [])],(r.get('floor') or {}).get('sequence'), r.get('dimensions'))
print('tags',len(md['mattertags']),md['mattertags'][:3]); print('locs',len(md['locations']), md['locations'][:2])
print('assets', json.dumps(md['assets'])[:1500]); print(md['geolocation'], md['image'])
