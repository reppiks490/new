import test from 'node:test';
import assert from 'node:assert/strict';
import {browserPerformanceProfile,limitBrowserTexture} from '../app/studio/web/browser-performance.js';

const environment=(coarse,width,ratio)=>({devicePixelRatio:ratio,matchMedia:query=>({matches:query.includes('pointer')?coarse:width<=760})});

test('phone startup defers model restoration and bounds graphics and texture buffers',()=>{
  const profile=browserPerformanceProfile(environment(true,390,3));
  assert.equal(profile.deferStartupModel,true);
  assert.equal(profile.pixelRatio,1);
  assert.equal(profile.antialias,false);
  assert.equal(profile.shadows,false);
  assert.equal(profile.preserveDrawingBuffer,false);
  assert.equal(profile.maxTextureSize,512);
});

test('desktop keeps its existing quality and automatic restoration',()=>{
  const profile=browserPerformanceProfile(environment(false,1440,3));
  assert.equal(profile.deferStartupModel,false);
  assert.equal(profile.pixelRatio,2);
  assert.equal(profile.antialias,true);
  assert.equal(profile.shadows,true);
  assert.equal(profile.preserveDrawingBuffer,true);
  assert.equal(profile.maxTextureSize,Infinity);
});

test('small windows and coarse-pointer tablets use the bounded profile',()=>{
  assert.equal(browserPerformanceProfile(environment(false,640,1)).deferStartupModel,true);
  assert.equal(browserPerformanceProfile(environment(true,1200,2)).deferStartupModel,true);
});

test('large textures are resampled in aspect ratio before GPU upload',()=>{
  const original={width:2048,height:1024};let drawn;
  const canvas={getContext:()=>({drawImage:(...args)=>{drawn=args;}})};
  const texture={image:original};
  assert.equal(limitBrowserTexture(texture,512,{createElement:()=>canvas}),texture);
  assert.equal(texture.image,canvas);
  assert.equal(canvas.width,512);assert.equal(canvas.height,256);
  assert.deepEqual(drawn,[original,0,0,512,256]);
  assert.equal(texture.needsUpdate,true);
});

test('small textures and desktop textures retain their original image',()=>{
  for(const [image,budget] of [[{width:128,height:128},512],[{width:2048,height:2048},Infinity]]){
    const texture={image};limitBrowserTexture(texture,budget,{createElement:()=>{throw Error('unexpected allocation');}});
    assert.equal(texture.image,image);
  }
});
