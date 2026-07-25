// @ant-design/x 的部分组件从 antd 顶层入口导入依赖。这里仅暴露当前聊天界面实际使用的组件，
// 避免将未使用的 Ant Design 组件一并纳入聊天分包。
export { default as Avatar } from 'antd/es/avatar'
export { default as Button } from 'antd/es/button'
export { default as ConfigProvider } from 'antd/es/config-provider'
export { default as Dropdown } from 'antd/es/dropdown'
export { default as Flex } from 'antd/es/flex'
export { default as Input } from 'antd/es/input'
export { default as Typography } from 'antd/es/typography'
export { default as theme } from 'antd/es/theme'
