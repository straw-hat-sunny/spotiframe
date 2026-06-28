FROM golang:1.26.4-alpine AS build

WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/spotiframe .

FROM alpine:3.23

RUN apk add --no-cache ca-certificates \
    && addgroup -S spotiframe \
    && adduser -S -G spotiframe spotiframe \
    && mkdir -p /data \
    && chown spotiframe:spotiframe /data

COPY --from=build /out/spotiframe /usr/local/bin/spotiframe

USER spotiframe
WORKDIR /data

EXPOSE 8080

ENTRYPOINT ["spotiframe"]
