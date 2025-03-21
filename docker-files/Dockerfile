FROM ubuntu:noble

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    cmake \
    g++ \
    gcc \
    make \
    doxygen \
    locate \
    qmake6 \
    git \
    qt6-base-dev \
    qt6-base-dev-tools \
    qt6-documentation-tools \
    qt6-declarative-dev \
    qt6-declarative-dev-tools \
    qt6-image-formats-plugins \
    qt6-l10n-tools \
    qt6-translations-l10n \
    qbs \
    gcovr \
    lcov \
    openjdk-17-jre \
    python3 \
    python3-pip \
    python3-venv \
    pipx \
    curl \
    unzip \
    x11-apps \
    net-tools \
    iputils-ping \
    libxcb-cursor0 \
    iftop \
    nethogs \
    tcpdump \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python3 -m venv ~/.virtualenvs/vibb_sim \
 && . ~/.virtualenvs/vibb_sim/bin/activate \
 && pip3 install "coverxygen==1.8.1" \
 && pip3 install "conan==2.9.3" \
 && pip3 install "spacepackets" \
 && pip3 install "prompt_toolkit" \
 && pip3 install "tmtccmd" \
 && pip3 install "PyQt6"

ENV VIRTUAL_ENV=/root/.virtualenvs/vibb_sim
ENV PATH=/root/.local/bin:/root/.virtualenvs/vibb_sim/bin:$PATH

RUN qbs setup-toolchains --detect && qbs setup-qt /usr/bin/qmake6 qt-6-4-2-bin && qbs config defaultProfile qt-6-4-2-bin \
  && conan profile detect --force

#COPY vibb_sim /opt/vibb_sim/
#WORKDIR /opt/vibb_sim/deps
#RUN ls -las > afile.txt
#RUN /opt/vibb_sim/deps/install_spacepackets.sh
#RUN /opt/vibb_sim/deps/install_tmtccmd.sh

#RUN cd /scratch/vibb_sim
#RUN ls -las >scratch-data.txt

