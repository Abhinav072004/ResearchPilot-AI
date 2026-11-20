FROM node:24-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN --mount=type=secret,id=researchpilot_build_ca \
    if [ -s /run/secrets/researchpilot_build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/researchpilot_build_ca; fi \
    && npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /src/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
