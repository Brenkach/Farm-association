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

## Розгортання через Helm

Чарт лежить у каталозі `helm/farm-association`. Він створює той самий набір об'єктів, що й маніфести з `k8s/`, але імена об'єктів будуються з імені релізу, а всі параметри винесено у values.

```
helm/farm-association/
├── Chart.yaml
├── values.yaml           # значення за замовчуванням (середовище розробки)
├── values-dev.yaml       # середовище розробки
├── values-prod.yaml      # продакшн-середовище
└── templates/
    ├── _helpers.tpl      # спільні шаблони: імена та мітки
    ├── NOTES.txt         # підказка після встановлення
    ├── configmap.yaml
    ├── secret.yaml
    ├── deployment.yaml
    ├── service.yaml
    ├── ingress.yaml              # створюється, якщо ingress.enabled
    ├── postgres-deployment.yaml
    ├── postgres-service.yaml
    ├── postgres-pvc.yaml         # створюється, якщо postgres.persistence.enabled
    ├── pre-upgrade-job.yaml      # хук pre-upgrade
    └── tests/test-health.yaml    # тест для helm test
```

### version і appVersion

У `Chart.yaml` є дві різні версії:

- `version` — версія самого чарта, тобто шаблонів і значень за замовчуванням. Її змінюють, коли змінюється чарт: додано шаблон, змінено мітки, політику хуків тощо. Наприклад, зміна політики видалення хуків підняла версію чарта з 0.1.0 до 0.1.1, хоча сам застосунок не змінився.
- `appVersion` — версія застосунку, яку чарт розгортає за замовчуванням (тег Docker-образу `farm-association`). Зараз це `1.0.0`. Якщо в values задано `image.tag`, розгортається саме він, а `appVersion` лише показується в `helm list`.

Отже, один і той самий чарт 0.1.1 може розгорнути застосунок 1.0.0 або 1.1.0, а нова версія застосунку не вимагає обов'язкової зміни чарта.

### Встановлення

Образи `farm-association:1.0.0` і `farm-association:1.1.0` мають бути завантажені в minikube (див. розділ вище).

```bash
# перевірка чарта
helm lint helm/farm-association

# середовище розробки
helm install farm helm/farm-association -n farm-helm --create-namespace \
  -f helm/farm-association/values-dev.yaml

# продакшн-середовище
helm install farm helm/farm-association -n farm-helm --create-namespace \
  -f helm/farm-association/values-prod.yaml \
  --set secret.pgPassword=<пароль> --set secret.secretKey=<ключ>

# перегляд маніфестів без встановлення
helm template farm helm/farm-association -f helm/farm-association/values-prod.yaml
```

Керування релізом:

```bash
helm list -n farm-helm
helm status farm -n farm-helm
helm get values farm -n farm-helm
helm upgrade farm helm/farm-association -n farm-helm -f helm/farm-association/values-dev.yaml --set image.tag=1.0.0
helm history farm -n farm-helm
helm rollback farm <ревізія> -n farm-helm
helm test farm -n farm-helm
helm uninstall farm -n farm-helm
```

### Пріоритет значень

Helm об'єднує значення в такому порядку, і кожне наступне джерело перекриває попереднє:

1. `values.yaml` у чарті (найнижчий пріоритет);
2. файли `-f`/`--values` у порядку, в якому їх передано (наступний файл перекриває попередній);
3. прапорці `--set`, `--set-string`, `--set-file` (найвищий пріоритет).

Наприклад, у команді `-f values-dev.yaml --set image.tag=1.0.0` тег береться з `--set` (1.0.0), а не з values-dev.yaml (1.1.0). Решта значень береться з values-dev.yaml, а те, чого немає в ньому, — з values.yaml.

### Параметри values

| Параметр | За замовчуванням | dev | prod | Опис |
| --- | --- | --- | --- | --- |
| `replicaCount` | `1` | `1` | `3` | кількість реплік застосунку |
| `image.repository` | `farm-association` | | | репозиторій образу |
| `image.tag` | `1.0.0` | `1.1.0` | `1.0.0` | тег образу; якщо порожній — `appVersion` |
| `image.pullPolicy` | `IfNotPresent` | | | політика завантаження образу |
| `service.type` | `ClusterIP` | | | тип Service |
| `service.port` | `80` | | | порт Service |
| `service.targetPort` | `5000` | | | порт контейнера |
| `resources.requests` | `100m` / `128Mi` | `100m` / `128Mi` | `250m` / `256Mi` | гарантовані ресурси |
| `resources.limits` | `500m` / `256Mi` | `500m` / `256Mi` | `1` / `512Mi` | граничні ресурси |
| `probes.path` | `/health` | | | шлях readiness- і liveness-проб |
| `config.pgHost` | порожньо | | | хост БД; порожньо — Service бази цього релізу |
| `config.pgPort` | `5432` | | | порт БД |
| `config.pgDatabase` | `farm_db` | | | назва бази даних |
| `config.pgUser` | `postgres` | | | користувач БД |
| `secret.pgPassword` | навчальне значення | | передавати через `--set` | пароль БД (у Secret) |
| `secret.secretKey` | навчальне значення | | передавати через `--set` | ключ Flask (у Secret) |
| `ingress.enabled` | `false` | `false` | `true` | створювати Ingress |
| `ingress.className` | `nginx` | | `nginx` | клас Ingress |
| `ingress.host` | `farm-dev.local` | | `farm.local` | доменне ім'я |
| `rollingUpdate.maxUnavailable` | `0` | | | стратегія оновлення |
| `rollingUpdate.maxSurge` | `1` | | | стратегія оновлення |
| `postgres.image` | `postgres:15-alpine` | | | образ PostgreSQL |
| `postgres.persistence.enabled` | `true` | | | створювати PVC для БД |
| `postgres.persistence.size` | `1Gi` | `1Gi` | | розмір PVC |
| `hooks.preUpgrade.enabled` | `true` | | | хук перевірки БД перед оновленням |

Порожня клітинка означає, що значення береться з `values.yaml`. Значення в Secret навчальні; реальні паролі у файлах значень не зберігаються і передаються через `--set`.

### Хук і тест

- `pre-upgrade-job.yaml` — Job з анотацією `helm.sh/hook: pre-upgrade`. Перед кожним `helm upgrade` він перевіряє, що база даних приймає з'єднання (`pg_isready`); якщо ні, оновлення не виконується.
- `tests/test-health.yaml` — Pod з анотацією `helm.sh/hook: test`. Команда `helm test` запускає його, і він перевіряє, що Service застосунку відповідає на `/health` зі статусом `ok`.

Обидва об'єкти мають політику `before-hook-creation,hook-succeeded`, тому після успішного виконання видаляються і не залишаються в namespace після `helm uninstall`.
