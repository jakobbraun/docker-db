FROM centos:7.5.1804

MAINTAINER EXASOL "service@exasol.com"

RUN yum update -y --exclude=kernel* && \
    yum install -y \
    epel-release \
    java-1.8.0-openjdk-headless \
    openssh-server \
    openssh-clients \
    which \
    sudo \
    vim \
    tar \
    man \
    iproute \
    strace \
    mtr \
    lvm2 \
    rsync && \
    yum clean all

RUN yum --disablerepo=epel -y update ca-certificates && \
    yum install -y \
    python-pam 

LABEL name="EXASOL DB Docker Image"  \
      version="6.1.1-d1" \
      dbversion="6.1.1" \
      osversion="6.1.1" \
      reversion="6.1.1" \
      license="Proprietary" \
      vendor="EXASOL AG"


COPY license/license.xml     /.license.xml
ADD EXAClusterOS-6.1.1_LS-DOCKER-CentOS-7.5.1804_x86_64.tar.gz              /
ENV PATH=/usr/opt/EXASuite-6/EXAClusterOS-6.1.1/bin:/usr/opt/EXASuite-6/EXAClusterOS-6.1.1/sbin:/usr/opt/EXASuite-6/EXARuntime-6.1.1/bin:/usr/opt/EXASuite-6/EXARuntime-6.1.1/sbin:/usr/opt/EXASuite-6/EXASolution-6.1.1/bin/Console:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    MANPATH=/usr/opt/EXASuite-6/EXAClusterOS-6.1.1/man:/usr/local/share/man:/usr/share/man \
    EXA_IMG_VERSION="6.1.1-d1" \
    EXA_DB_VERSION="6.1.1" \
    EXA_OS_VERSION="6.1.1" \
    EXA_RE_VERSION="6.1.1" 

ENTRYPOINT ["/usr/opt/EXASuite-6/EXAClusterOS-6.1.1/devel/docker/exadt"]
CMD ["init-sc"]
