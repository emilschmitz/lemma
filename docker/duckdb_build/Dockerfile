# Build environment of the portable DuckDB binaries (scripts/release/build_portable.sh): the base image DuckDB's own linux_amd64 release
# builds use (db_extension/duckdb_ext/extension-ci-tools/docker/linux_amd64/Dockerfile: quay.io/pypa/manylinux_2_28_x86_64 = AlmaLinux 8,
# glibc 2.28, gcc-toolset-14), without their vcpkg/AWS/Java extras: the Lemma extension has no third-party dependencies.
# Pinned by digest so a rebuild uses the same compiler and glibc.
FROM quay.io/pypa/manylinux_2_28_x86_64@sha256:f6adcfd450f0927a05c66ded9b4c3bb538fbab625b1ca3f35d71ac093b24b57f
RUN yum install -y ninja-build git && yum clean all
ENV GEN=ninja
WORKDIR /src
