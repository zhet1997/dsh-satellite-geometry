export const MAX_SELECTION_COMPONENTS = 2000
export const SELECTION_PAGE_SIZE = 100

export function selectionProblem(payload, requireSelection = false) {
  if (typeof payload?.projectId !== 'string' || !payload.projectId) return '请先打开一个卫星项目。'
  if (!Array.isArray(payload.selection)) return '无法读取所选组件，请重新选择后带入。'
  if (payload.selection.length > MAX_SELECTION_COMPONENTS) return `一次最多带入 ${MAX_SELECTION_COMPONENTS} 个组件，请分批选择。`
  if (requireSelection && !payload.selection.length) return '请先选择组件再带入聊天；阅读整个项目的资料时，请在聊天中说明项目名称。'
  return ''
}
