FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
# 国内服务器走清华镜像加速；海外服务器可删掉 -i 参数
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY wechat_bot ./wechat_bot

EXPOSE 9919

CMD ["python", "-m", "wechat_bot.main"]
