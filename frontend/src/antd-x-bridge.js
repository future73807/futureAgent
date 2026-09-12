// @ant-design/x 的部分组件从 antd 顶层入口导入依赖。这里仅暴露这些组件实际需要的导出，
// 避免把未使用的 Ant Design 组件一并纳入聊天分包。
//
// 下面这份清单是按 @ant-design/x 的真实 import 语句核对出来的，不是猜的。
// 侧边栏合并后 Conversations / Attachments 被提前加载（不再只在懒加载的对话页里），
// 少一个导出就会让构建直接报 MISSING_EXPORT。升级 @ant-design/x 后请重新核对：
//   Get-ChildItem node_modules/@ant-design/x/es -Recurse -Filter *.js |
//     Select-String "from 'antd'"
export { default as Avatar } from 'antd/es/avatar'
export { default as Button } from 'antd/es/button'
export { default as Cascader } from 'antd/es/cascader'
export { default as ConfigProvider } from 'antd/es/config-provider'
export { default as Dropdown } from 'antd/es/dropdown'
export { default as Flex } from 'antd/es/flex'
export { default as Image } from 'antd/es/image'
export { default as Input } from 'antd/es/input'
export { default as Progress } from 'antd/es/progress'
export { default as Tooltip } from 'antd/es/tooltip'
export { default as Typography } from 'antd/es/typography'
export { default as Upload } from 'antd/es/upload'
export { default as theme } from 'antd/es/theme'
export { default as version } from 'antd/es/version'
