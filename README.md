# Farm-association

Веб-застосунок на Flask + PostgreSQL.

## Розгортання в Kubernetes (minikube)

Маніфести лежать у каталозі `k8s/`, по одному файлу на об'єкт. Номер у назві файлу задає порядок створення.

| Файл | Об'єкт |
| --- | --- |
| `00-namespace.yaml` | Namespace `farm-association` |
| `01-configmap.yaml` | ConfigMap `farm-config` |
| `02-secret.yaml` | Secret `farm-secret` |
| `03-postgres-pvc.yaml` | PersistentVolumeClaim `postgres-data` (1 Gi) |
| `04-postgres-deployment.yaml` | Deployment `postgres` |
| `05-postgres-service.yaml` | Service `postgres` (ClusterIP, 5432) |
| `06-app-deployment.yaml` | Deployment `farm-web` (2 репліки, проби, ліміти) |
| `07-app-service.yaml` | Service `farm-web` (ClusterIP, 80 → 5000) |
| `08-ingress.yaml` | Ingress `farm-web` (host `farm.local`) |

### Порядок розгортання

1. Запустити кластер і увімкнути доповнення:

   ```bash
   minikube start --driver=docker
   minikube addons enable metrics-server
   minikube addons enable ingress
   ```

2. Зібрати образи застосунку і завантажити їх у minikube (тег `latest` не використовується):

   ```bash
   docker build --load -t farm-association:1.0.0 .
   minikube image load farm-association:1.0.0
   ```

   Версія 1.1.0 збирається так само після зміни `APP_VERSION` в `app.py`.

3. Застосувати всі маніфести однією командою:

   ```bash
   kubectl apply -f k8s/
   kubectl get pods -n farm-association -w
   ```

4. Відкрити доступ із хоста. В окремому терміналі запустити тунель і не закривати його:

   ```bash
   minikube tunnel
   ```

   Додати домен у `/etc/hosts`:

   ```bash
   echo "127.0.0.1 farm.local" | sudo tee -a /etc/hosts
   ```

   Застосунок доступний за адресою http://farm.local, перевірка стану — http://farm.local/health.

### Параметри конфігурації

**ConfigMap `farm-config`** (передається в контейнер як змінні оточення):

| Параметр | Значення | Призначення |
| --- | --- | --- |
| `PG_HOST` | `postgres` | ім'я Service бази даних |
| `PG_PORT` | `5432` | порт PostgreSQL |
| `PG_DATABASE` | `farm_db` | назва бази даних |
| `PG_USER` | `postgres` | користувач бази даних |

**Secret `farm-secret`** (передається як змінні оточення):

| Параметр | Призначення |
| --- | --- |
| `PG_PASSWORD` | пароль користувача PostgreSQL (також використовується контейнером `postgres`) |
| `SECRET_KEY` | секретний ключ Flask для підпису сесій |

Значення в Secret навчальні й не збігаються з паролями реальних систем.

### Корисні команди

```bash
# стан об'єктів
kubectl get pods,deploy,rs,svc,ingress,pvc -n farm-association

# оновлення версії та відкат
kubectl set image deployment/farm-web web=farm-association:1.1.0 -n farm-association
kubectl rollout status deployment/farm-web -n farm-association
kubectl rollout history deployment/farm-web -n farm-association
kubectl rollout undo deployment/farm-web -n farm-association

# видалення всього
kubectl delete -f k8s/
```
