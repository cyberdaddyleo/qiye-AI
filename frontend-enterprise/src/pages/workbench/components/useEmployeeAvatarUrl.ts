import { useEffect, useState } from 'react';

import { api } from '@/api/client';
import { getEnterpriseAuthSession } from '@/auth';

const avatarBlobCache = new Map<string, Promise<Blob>>();

function avatarCacheKey(pointer: string): string {
  const user = getEnterpriseAuthSession()?.user;
  return `${user?.tenant_id || ''}:${user?.id || ''}:${pointer}`;
}

function loadEmployeeAvatar(pointer: string): Promise<Blob> {
  const key = avatarCacheKey(pointer);
  const cached = avatarBlobCache.get(key);
  if (cached) return cached;

  const request = api.blob(pointer);
  avatarBlobCache.set(key, request);
  void request.catch(() => {
    if (avatarBlobCache.get(key) === request) avatarBlobCache.delete(key);
  });
  return request;
}

export default function useEmployeeAvatarUrl(pointer?: string | null): string {
  const [avatarUrl, setAvatarUrl] = useState('');

  useEffect(() => {
    let active = true;
    let objectUrl = '';
    setAvatarUrl('');
    if (!pointer) return undefined;

    void loadEmployeeAvatar(pointer).then((blob) => {
      if (!active) return;
      objectUrl = URL.createObjectURL(blob);
      setAvatarUrl(objectUrl);
    }).catch(() => {
      if (active) setAvatarUrl('');
    });

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [pointer]);

  return avatarUrl;
}
