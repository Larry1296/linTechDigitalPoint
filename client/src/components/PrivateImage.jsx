import { useEffect, useState } from 'react';
import { privateBlob } from '../core/api/client';

export function PrivateImage({ src, alt, ...props }) {
  const [blob, setBlob] = useState(null);
  const privatePath = typeof src === 'string' && src.startsWith('/media/');
  useEffect(() => {
    if (!privatePath) return;
    const controller = new AbortController();
    let url;
    privateBlob(src, controller.signal).then(data => {
      if (controller.signal.aborted) return;
      url=URL.createObjectURL(data);setBlob({src,url});
    }).catch(() => {});
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [src, privatePath]);
  return <img {...props} src={privatePath ? (blob?.src === src ? blob.url : undefined) : src} alt={alt} />;
}
