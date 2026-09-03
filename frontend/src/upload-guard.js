// 附件上传的前端即时校验：类型与大小与后端约束保持一致。
export const ALLOWED_UPLOAD_EXTENSIONS = ['.txt', '.md', '.csv', '.json', '.pdf', '.docx', '.xlsx', '.png', '.jpg', '.jpeg', '.webp']

export function validateUpload(file, { maxMb = 20 } = {}) {
  const name = String(file?.name || '').toLowerCase()
  const dot = name.lastIndexOf('.')
  const ext = dot >= 0 ? name.slice(dot) : ''
  if (!ALLOWED_UPLOAD_EXTENSIONS.includes(ext)) {
    return `暂不支持 ${ext || '该'} 类型文件；支持文本、PDF、Office 文档与图片`
  }
  if (Number(file?.size || 0) > maxMb * 1024 * 1024) {
    return `文件超过 ${maxMb} MB 大小限制`
  }
  return ''
}
