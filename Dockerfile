FROM nvidia/cuda:10.2-cudnn7-runtime-ubuntu18.04
ENV PATH="/root/miniconda3/bin:${PATH}"
ARG PATH="/root/miniconda3/bin:${PATH}"

RUN apt update \
    && apt install -y htop python3-dev wget git imagemagick

RUN wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh \
    && mkdir root/.conda \
    && sh Miniconda3-latest-Linux-x86_64.sh -b \
    && rm -f Miniconda3-latest-Linux-x86_64.sh \
    && conda create -y -n .venv python=3.7

COPY . TUM-ADLR-SS21-01/

 # Installation of packages needed for rokin for 3d kinematics
ENV EIGEN_INCLUDE_DIR="/usr/include/eigen3/"
RUN apt install -y libeigen3-dev\
    && apt install -y swig \
    && apt install -y gfortran

WORKDIR /TUM-ADLR-SS21-01

RUN /bin/bash -c "source activate .venv \
    && pip install -r requirements.txt \
    && pip install git+https://github.com/scleronomic/rokin@stable1.0 \
    && pip install git+https://github.com/VLL-HD/FrEIA@v0.2"

# Needed for rokin to not throw an error, modify if you want to use meshes
ENV ROKIN_MESH_DIR="your/path/to/the/meshes/"