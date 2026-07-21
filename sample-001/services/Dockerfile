# syntax=docker/dockerfile:1.7
FROM golang:1.26.5-alpine3.23@sha256:622e56dbc11a8cfe87cafa2331e9a201877271cbff918af53d3be315f3da88cc AS build
WORKDIR /src
ENV CGO_ENABLED=0
COPY go.mod go.sum ./
RUN go mod download
COPY . .

FROM build AS build-bff
RUN go build -trimpath -ldflags="-s -w" -o /out/service ./cmd/bff
FROM build AS build-api
RUN go build -trimpath -ldflags="-s -w" -o /out/service ./cmd/api
FROM build AS build-fake-scanner
RUN go build -trimpath -ldflags="-s -w" -o /out/service ./cmd/scanner
FROM build AS build-promotion
RUN go build -trimpath -ldflags="-s -w" -o /out/service ./cmd/promotion
FROM build AS build-deletion
RUN go build -trimpath -ldflags="-s -w" -o /out/service ./cmd/deletion
FROM build AS build-reconciliation
RUN go build -trimpath -ldflags="-s -w" -o /out/service ./cmd/reconciliation
FROM build AS build-fake-oidc
RUN go build -trimpath -ldflags="-s -w" -o /out/service ./cmd/fake-oidc
FROM build AS build-goose
RUN go build -trimpath -ldflags="-s -w" -o /out/goose github.com/pressly/goose/v3/cmd/goose

FROM scratch AS bff-demo
COPY --from=build-bff /out/service /service
USER 65532:65532
ENTRYPOINT ["/service"]
FROM bff-demo AS bff-development
FROM bff-demo AS bff

FROM scratch AS api-demo
COPY --from=build-api /out/service /service
USER 65532:65532
ENTRYPOINT ["/service"]
FROM api-demo AS api-development
FROM api-demo AS api

FROM scratch AS fake-scanner-demo
COPY --from=build-fake-scanner /out/service /service
USER 65532:65532
ENTRYPOINT ["/service"]
FROM fake-scanner-demo AS fake-scanner-development

FROM scratch AS promotion-demo
COPY --from=build-promotion /out/service /service
USER 65532:65532
ENTRYPOINT ["/service"]
FROM promotion-demo AS promotion-development
FROM promotion-demo AS promotion

FROM scratch AS deletion-demo
COPY --from=build-deletion /out/service /service
USER 65532:65532
ENTRYPOINT ["/service"]
FROM deletion-demo AS deletion-development
FROM deletion-demo AS deletion

FROM scratch AS reconciliation-demo
COPY --from=build-reconciliation /out/service /service
USER 65532:65532
ENTRYPOINT ["/service"]
FROM reconciliation-demo AS reconciliation-development
FROM reconciliation-demo AS reconciliation

# The fake is deliberately unavailable as a production-shaped target.
FROM scratch AS fake-oidc-development
COPY --from=build-fake-oidc /out/service /service
USER 65532:65532
ENTRYPOINT ["/service"]

FROM scratch AS migrate-development
COPY --from=build-goose /out/goose /goose
USER 65532:65532
ENTRYPOINT ["/goose"]

# CI packaging consumes the exact binaries produced by the validated go-build job.
FROM scratch AS bff-prebuilt
COPY build/bff /service
USER 65532:65532
ENTRYPOINT ["/service"]
FROM scratch AS api-prebuilt
COPY build/api /service
USER 65532:65532
ENTRYPOINT ["/service"]
FROM scratch AS fake-scanner-prebuilt
COPY build/scanner /service
USER 65532:65532
ENTRYPOINT ["/service"]
FROM scratch AS promotion-prebuilt
COPY build/promotion /service
USER 65532:65532
ENTRYPOINT ["/service"]
FROM scratch AS deletion-prebuilt
COPY build/deletion /service
USER 65532:65532
ENTRYPOINT ["/service"]
FROM scratch AS reconciliation-prebuilt
COPY build/reconciliation /service
USER 65532:65532
ENTRYPOINT ["/service"]
