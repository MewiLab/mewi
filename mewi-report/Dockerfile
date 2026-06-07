FROM node:20-alpine AS deps

WORKDIR /app

ENV ASTRO_TELEMETRY_DISABLED=1

COPY package.json package-lock.json ./
RUN npm ci

FROM deps AS dev

COPY . .

EXPOSE 4321

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "4321"]

FROM deps AS build

COPY . .
RUN npm run build

FROM node:20-alpine AS runner

WORKDIR /app

ENV ASTRO_TELEMETRY_DISABLED=1
ENV NODE_ENV=production
ENV HOST=0.0.0.0
ENV PORT=4321

COPY --from=deps /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY package.json package-lock.json ./

EXPOSE 4321

CMD ["node", "./dist/server/entry.mjs"]
