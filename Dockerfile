FROM python:3.12-slim
WORKDIR /work
COPY hippo/ /work/hippo/
ENTRYPOINT ["python", "-m", "hippo"]
CMD ["--pharmacies", "/work/data/pharmacies", "--claims", "/work/data/claims", "--reverts", "/work/data/reverts", "--output", "/work/output"]
