'use strict';
(function (root) {
  function dimensions(sourceWidth, sourceHeight, shortSide) {
    if (![sourceWidth,sourceHeight,shortSide].every(Number.isSafeInteger) || Math.min(sourceWidth,sourceHeight) < 1 || ![1024,2048,3072,4096].includes(shortSide)) throw new Error('Dimensions ou résolution invalides.');
    const scale=shortSide/Math.min(sourceWidth,sourceHeight);
    const width=Math.round(sourceWidth*scale), height=Math.round(sourceHeight*scale);
    const engineWidth=Math.ceil(width/32)*32, engineHeight=Math.ceil(height/32)*32;
    if (Math.max(engineWidth,engineHeight)>16384 || engineWidth*engineHeight>67108864) throw new Error('Ce format dépasse la limite de dimensions. Choisissez une résolution inférieure.');
    return {width,height,engineWidth,engineHeight,shortSide};
  }
  const api={dimensions};
  if(typeof module==='object' && module.exports) module.exports=api;
  else root.QwenResolution=api;
})(typeof window==='undefined' ? this : window);
