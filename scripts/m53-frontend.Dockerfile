FROM military-stt/central-frontend:before-m53-20261021
RUN rm -rf /usr/share/nginx/html/assets /usr/share/nginx/html/index.html
COPY . /usr/share/nginx/html/
