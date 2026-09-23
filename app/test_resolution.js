const assert=require('node:assert/strict');
const {dimensions}=require('./resolution.js');
for (const [w,h,k,ow,oh] of [[3000,2000,1024,1536,1024],[2000,3000,1024,1024,1536],[3000,2000,2048,3072,2048],[2000,3000,3072,3072,4608],[3000,2000,4096,6144,4096],[4000,3000,1024,1365,1024],[1920,1080,2048,3641,2048],[1,1,4096,4096,4096]]) {
 const d=dimensions(w,h,k); assert.equal(d.width,ow);assert.equal(d.height,oh);assert.equal(Math.min(d.width,d.height),k);assert.equal(d.engineWidth%32,0);assert.equal(d.engineHeight%32,0);assert.ok(d.engineWidth-d.width>=0&&d.engineWidth-d.width<32);assert.ok(d.engineHeight-d.height>=0&&d.engineHeight-d.height<32);
}
assert.throws(()=>dimensions(100,1,4096));assert.throws(()=>dimensions(1,1,NaN));assert.throws(()=>dimensions(0,1,1024));
console.log('Résolutions vérifiées : paysage, portrait, carré, arrondi au pixel, alignement et limites.');
