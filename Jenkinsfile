pipeline {
    agent any

    environment {
        IMAGE_NAME = "llmops-api"
        IMAGE_TAG  = "0.0.${BUILD_NUMBER}"
        DEPLOY_COMPOSE_FILE = "./jenkins/docker-compose.yaml"

        // 代理配置：在 Jenkins「系统管理 → 系统配置 → 全局属性 → 环境变量」里统一维护
        // 或在节点上配置，这里直接读取宿主机环境变量
        PROXY_HOST = "${env.BUILD_PROXY ?: 'http://127.0.0.1:7890'}"
    }

    stages {

        stage('Checkout') {
            steps {
                echo "Checking out source code..."
                checkout scm
            }
        }

        stage('Show Python Version') {
            steps {
                script {
                    sh "python3 --version || true"
                }
            }
        }

        stage('Build Docker Image') {
            steps {
                script {
                    echo "Building Docker image ${IMAGE_NAME}:${IMAGE_TAG}..."
                    sh """
                        docker build \\
                          --build-arg HTTP_PROXY=${PROXY_HOST} \\
                          --build-arg HTTPS_PROXY=${PROXY_HOST} \\
                          --build-arg NO_PROXY=localhost,127.0.0.1,deb.debian.org,security.debian.org,mirrors.tencent.com,mirrors.cloud.tencent.com \\
                          --provenance=false \\
                          -t ${IMAGE_NAME}:${IMAGE_TAG} \\
                          .
                    """
                }
            }
        }

        stage('Deploy via Docker Compose') {
            steps {
                script {
                    echo "Deploying container using docker compose..."

                    // 读取 deploy.env 文件
                    def initDb = 'false'  // 默认值
                    def configFile = "${WORKSPACE}/deploy.env"
                    if (fileExists(configFile)) {
                        def props = readFile(configFile).split("\\n")
                        props.each { line ->
                            line = line.trim()
                            if (!line.startsWith("#") && line.contains("=")) {
                                def (key, value) = line.split("=")
                                if (key.trim() == "INIT_DB") {
                                    initDb = value.trim().toLowerCase()
                                }
                            }
                        }
                    }
                    echo "INIT_DB=${initDb}"
                    // 如果配置需要初始化数据库
                    if (initDb == 'true') {
                        echo "Initializing database..."
                        // 停止旧容器
                        sh "docker compose -f ${DEPLOY_COMPOSE_FILE} down"

                        sh """
                            IMAGE_TAG=${IMAGE_TAG} docker compose -f ${DEPLOY_COMPOSE_FILE} up -d --build
                        """
                    } else {
                        echo "Skipping database initialization."
                        // 停止旧容器
                        sh "docker compose -f ${DEPLOY_COMPOSE_FILE} rm -sf llmops-api llmops-celery"

                        sh """
                            IMAGE_TAG=${IMAGE_TAG} docker compose -f ${DEPLOY_COMPOSE_FILE} up llmops-api llmops-celery llmops-nginx -d --build
                        """
                    }
                }
            }
        }

        stage('Clean Docker Image') {
            steps {
                script {
                    echo "Cleaning Docker images..."
                    sh """
                        # 清理本次构建镜像
                        docker rmi -f ${IMAGE_NAME}:${IMAGE_TAG} || true

                        # 清理多阶段构建产生的悬空镜像（<none>:<none>）
                        docker image prune -f || true
                    """
                }
            }
        }
    }

    post {
        success {
            echo "✅ Pipeline finished successfully! Image: ${IMAGE_NAME}:${IMAGE_TAG}"
        }
        failure {
            echo "❌ Pipeline failed! Check logs above."
            // 构建失败时也清理悬空镜像，避免磁盘堆积
            sh "docker image prune -f || true"
        }
    }
}