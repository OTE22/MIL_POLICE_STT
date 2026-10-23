# Isolated alignment-only experiment; never replace the agent with this image.
FROM military-stt/pyannote-evaluation:4.0.7
USER root
# The ASR/CUDA dependencies are unnecessary for whisperx.alignment. The tested
# base supplies torch, torchaudio, pandas, transformers and their dependencies.
COPY --from=whisperx_source / /opt/whisperx-source/
RUN python -m pip install --no-deps 'nltk==3.9.2'
ENV PYTHONPATH=/opt/whisperx-source
# Inputs already contain utterance spans; evaluation supplies a whole-span
# sentence splitter instead of downloading unrelated language tokenizers.
RUN python -c "from whisperx.alignment import align, load_align_model"
ENTRYPOINT ["python"]
HEALTHCHECK NONE
