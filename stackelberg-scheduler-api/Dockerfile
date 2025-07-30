FROM golang:1.21-alpine AS builder

WORKDIR /app

# Copy go mod and sum files
COPY go.mod go.sum ./

# Download dependencies
RUN go mod download

# Copy source code
COPY main.go ./
COPY pkg/ pkg/


# Build the scheduler
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o stackelberg-scheduler .

FROM alpine:latest

# Install ca-certificates for HTTPS calls to the API
RUN apk --no-cache add ca-certificates

WORKDIR /root/

# Copy the binary from builder
COPY --from=builder /app/stackelberg-scheduler .

# Create non-root user
RUN addgroup -g 1001 scheduler && \
    adduser -D -u 1001 -G scheduler scheduler

USER scheduler

EXPOSE 10259

CMD ["./stackelberg-scheduler"]