FROM node:24-alpine

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY . .
# Inside Compose the Vite proxy must reach the backend service, not localhost.
ENV VITE_API_PROXY_TARGET=http://backend:8000
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
