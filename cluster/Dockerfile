# Build stage: compile dqlite + raft + go-dqlite from source.
#
# We pin canonical/dqlite at v1.18.5 and apply one local patch
# (cluster/patches/0001-preserve-sqlite-null-type-for-null-values.patch,
# tracked upstream as https://github.com/canonical/dqlite/issues/882)
# so NULL cells in BOOLEAN / DATETIME columns serialise as
# SQLITE_NULL instead of being remapped to the declared-type wire tag.
# The patch is small; once #882 lands upstream and a release ships,
# bump DQLITE_VERSION below and drop the patch.
FROM golang:1.22-bookworm AS builder

RUN apt-get update && apt-get install -y \
    autoconf \
    automake \
    git \
    libtool \
    pkg-config \
    libsqlite3-dev \
    libuv1-dev \
    liblz4-dev \
    tcl \
    && rm -rf /var/lib/apt/lists/*

# Raft is dqlite's replication engine — clone + build at the
# canonical default branch. dqlite's configure script links against it.
RUN git clone https://github.com/canonical/raft.git /raft && \
    cd /raft && \
    autoreconf -i && \
    ./configure && \
    make && \
    make install

# Pin the dqlite version we build against. Bump this line + drop the
# patch when canonical/dqlite#882 lands upstream.
ARG DQLITE_VERSION=v1.18.5

COPY patches/ /patches/

RUN git clone https://github.com/canonical/dqlite.git /dqlite && \
    cd /dqlite && \
    git checkout "${DQLITE_VERSION}" && \
    git apply /patches/0001-preserve-sqlite-null-type-for-null-values.patch && \
    autoreconf -i && \
    ./configure && \
    make && \
    make install

RUN ldconfig

# go-dqlite ships a small demo server that wraps libdqlite. We use
# it as the per-node entry point — init-node.sh below invokes it
# with the right --db / --api / --join args.
RUN git clone https://github.com/canonical/go-dqlite.git /go-dqlite
WORKDIR /go-dqlite
RUN CGO_LDFLAGS_ALLOW="-Wl,-z,now" go build -tags libsqlite3 -o /dqlite-demo ./cmd/dqlite-demo


# Runtime stage: just the libraries + the demo binary + node scripts.
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    libsqlite3-0 \
    libuv1 \
    liblz4-1 \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/libraft.* /usr/local/lib/
COPY --from=builder /usr/local/lib/libdqlite.* /usr/local/lib/
COPY --from=builder /dqlite-demo /app/dqlite-demo
COPY scripts/init-node.sh /app/init-node.sh
COPY scripts/healthcheck.sh /app/healthcheck.sh

RUN ldconfig && chmod +x /app/*.sh

WORKDIR /data
ENTRYPOINT ["/app/init-node.sh"]
