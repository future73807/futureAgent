FROM nginx:alpine

# 移除默认配置
RUN rm /etc/nginx/conf.d/default.conf

# 使用自定义配置
COPY nginx.conf /etc/nginx/nginx.conf
