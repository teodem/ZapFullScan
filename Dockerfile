# This dockerfile builds the zap WEEKLY release
FROM ubuntu:16.04
LABEL maintainer="psiinon@gmail.com"

RUN apt-get update && apt-get install -q -y --fix-missing \
	make \
	automake \
	autoconf \
	gcc g++ \
	openjdk-8-jdk \
	ruby \
	wget \
	curl \
	xmlstarlet \
	unzip \
	git \
	openbox \
	xterm \
	net-tools \
	ruby-dev \
	python-pip \
	firefox \
	xvfb \
	x11vnc && \
	apt-get clean && \
	rm -rf /var/lib/apt/lists/*

RUN gem install zapr
RUN pip install --upgrade pip zapcli python-owasp-zap-v2.4

RUN useradd -d /home/zap -m -s /bin/bash zap
RUN echo zap:zap | chpasswd
RUN mkdir /zap && chown zap:zap /zap

WORKDIR /zap

#Change to the zap user so things get done as the right person (apart from copy)
USER zap

RUN mkdir /home/zap/.vnc

RUN curl -s https://raw.githubusercontent.com/zaproxy/zap-admin/master/ZapVersions.xml | xmlstarlet sel -t -v //url |grep -i weekly | wget --content-disposition -i - && \
	unzip *.zip && \
	rm *.zip && \
	cp -R ZAP*/* . &&  \
	rm -R ZAP* && \
	curl -s -L https://bitbucket.org/meszarv/webswing/downloads/webswing-2.3-distribution.zip > webswing.zip && \
	unzip *.zip && \
	rm *.zip && \
	touch AcceptedLicense


ENV JAVA_HOME /usr/lib/jvm/java-8-openjdk-amd64/
#ENV PATH $JAVA_HOME/bin:/zap/:$PATH
ENV PATH=/usr/lib/jvm/java-8-openjdk-amd64//bin:/zap/:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ENV ZAP_PATH /zap/zap.sh

# Default port for use with zapcli
ENV ZAP_PORT 8080
ENV HOME /home/zap/

COPY zap* /zap/
COPY webswing.config /zap/webswing-2.3/
COPY policies /home/zap/.ZAP_D/policies/
COPY .xinitrc /home/zap/

#Copy doesn't respect USER directives so we need to chown and to do that we need to be root
USER root

RUN chown zap:zap /zap/zap-x.sh && \
	chown zap:zap /zap/zap-baseline.py && \
	chown zap:zap /zap/zap-webswing.sh && \
	chown zap:zap /zap/webswing-2.3/webswing.config && \
	chown zap:zap -R /home/zap/.ZAP_D/ && \
	chown zap:zap /home/zap/.xinitrc && \
	chmod a+x /home/zap/.xinitrc

#Change back to zap at the end
USER zap

HEALTHCHECK --retries=5 --interval=5s CMD zap-cli status
