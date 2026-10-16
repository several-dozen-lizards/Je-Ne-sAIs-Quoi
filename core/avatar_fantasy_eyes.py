"""Procedural eye atlases shared by the designer and exported avatars."""
import base64,io
from functools import lru_cache
import numpy as np
from PIL import Image

@lru_cache(maxsize=16)
def render(style,shape,width,height,size,iris,accent,sclera,shading,inner,lightness=.5):
    n=1024;y,x=np.indices((n,n));u=x/n;v=y/n
    d1=np.hypot(u-.707,v-.298);d2=np.hypot(u-.290,v-.711)
    dx=u-np.where(d1<d2,.707,.290);dy=v-np.where(d1<d2,.298,.711)
    d=np.minimum(d1,d2);radius=(.078+.065*size)*.97+.18*max(0,2*size-1)**2;r=d/radius;theta=np.arctan2(dy,dx)
    def color(hex):return np.array([int(hex[i:i+2],16)/255 for i in [1,3,5]])
    def smooth(a,b,t):
        t=np.clip((t-a)/(b-a),0,1);return t*t*(3-2*t)
    upper=smooth(-.015,.115,-dy)
    shade=1-shading*(.10+.30*smooth(radius*.85,.225,d)+.36*upper+
                     .12*smooth(.10,.23,np.abs(dx))+.06*smooth(.10,.22,dy))
    rgb=np.ones((n,n,3))*.91*color(sclera)*shade[:,:,None]
    fiber=.5+.5*np.sin(theta*91+np.sin(theta*27)*3+r*19)
    fine=.5+.5*np.sin(theta*183-r*36)
    value=.36+.34*fiber+.18*fine
    blend=np.clip(.18+.25*np.sin(r*9+theta*3),0,1)
    if style=='ember':blend=np.clip(.75-r*.65+.22*fiber,0,1);value=.45+.5*fiber
    elif style=='galaxy':blend=.5+.5*np.sin(theta*3+r*13+np.sin(theta*5));value=.25+.4*fiber;value+=.65*((np.sin(u*1923+v*87)*np.sin(v*2147-u*163))>.985)
    elif style=='rings':blend=(.5+.5*np.cos(r*44))**5;value=.5+.3*fiber
    elif style=='crystal':blend=.5+.5*np.sin(np.floor(theta*7)*2+np.floor(r*7)*3);value=.4+.5*blend
    elif style=='spiral':blend=(.5+.5*np.sin(theta*4-r*24))**3;value=.55+.25*fiber
    elif style=='starburst':blend=(.5+.5*np.cos(theta*12))**7;value=.48+.35*fiber
    elif style=='void':blend=np.zeros_like(r);value=np.ones_like(r)*.04
    radial=smooth(.25,.85,r)[:,:,None]
    base=color(inner if inner!='#ffffff' else iris)*(1-radial)+color(iris)*radial
    iris_rgb=((1-blend[:,:,None])*base+blend[:,:,None]*color(accent))*value[:,:,None]
    iris_rgb*= (1-.65*smooth(.85,1,r))[:,:,None]
    iris_rgb=np.clip(iris_rgb*2**((lightness-.5)*3),0,1)
    iris_mask=1-smooth(.98,1.02,r)
    rgb=rgb*(1-iris_mask[:,:,None])+iris_rgb*iris_mask[:,:,None]
    w=.08+.62*width;h=.08+.72*height
    if shape=='vertical':w*=.42;h=.35+.6*height
    if shape=='horizontal':h*=.35;w=.35+.6*width
    px=dx/radius/w;py=dy/radius/h
    metric=abs(px)+abs(py) if shape=='diamond' else np.sqrt(px*px+py*py)
    pupil=(1-smooth(.92,1.04,metric))*iris_mask if shape!='none' else np.zeros_like(r)
    rgb=rgb*(1-pupil[:,:,None])+np.array([.008,.009,.012])*pupil[:,:,None]
    # The cornea/iris sits under the same upper lid as the sclera; do not leave
    # fantasy or radial irises glowing independently of the socket lighting.
    globe_shade=1-shading*(.02+.38*upper+.08*smooth(.85,1,r))
    rgb*=1-iris_mask[:,:,None]+iris_mask[:,:,None]*globe_shade[:,:,None]
    rgba=np.concatenate([np.rint(np.clip(rgb,0,1)*255).astype('uint8'),np.full((n,n,1),255,dtype='uint8')],axis=2)
    output=io.BytesIO();Image.fromarray(rgba).save(output,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode()

def resolve_fantasy(values):
    return render(*[values[k] for k in ['eye_style','pupil_shape','pupil_width','pupil_height','iris_size','iris','eye_accent','eyes','eye_shading','iris_inner','iris_lightness']])
