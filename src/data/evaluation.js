export async function api(path, body) {
  const response = await fetch(path, {
    ...(body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
    signal: AbortSignal.timeout(45000)
  });
  const content = await response.text();
  let data;
  try { data = JSON.parse(content); }
  catch { throw new Error('평가 API 응답이 없습니다. npm run dev로 Python API와 UI를 함께 실행하세요.'); }
  if (!response.ok) throw new Error(data.error || '평가 요청에 실패했습니다.');
  return data;
}
