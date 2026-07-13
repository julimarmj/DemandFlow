# ⚡ DemandFlow — Gestão de Demandas Profissional

Aplicativo desktop Python/PyQt6 para gerenciamento completo de demandas técnicas,
inspirado em Jira, Linear e ClickUp — focado em uso individual ou pequenas equipes.

---

## 🚀 Instalação Rápida

### 1. Pré-requisitos
- Python 3.11 ou superior
- pip atualizado

### 2. Clone / extraia o projeto
```bash
# Se recebeu como ZIP, extraia e entre na pasta:
cd demandflow
```

### 3. Crie um ambiente virtual (recomendado)
```bash
python -m venv venv

# Windows:
venv\Scripts\activate

# Linux / macOS:
source venv/bin/activate
```

### 4. Instale as dependências
```bash
pip install -r requirements.txt
```

### 5. Execute
```bash
python main.py
```

O banco de dados SQLite é criado automaticamente em `~/.demandflow/demandflow.db`
e já vem com 6 demandas de exemplo.

---

## 📁 Estrutura do Projeto

```
demandflow/
├── main.py                          ← Ponto de entrada
├── requirements.txt
│
├── core/                            ← Domínio (independente de framework)
│   ├── domain/
│   │   └── entities.py              ← Demand, Status, Priority, Comment...
│   ├── ports/
│   │   └── repositories.py          ← Interfaces (contratos)
│   └── usecases/
│       └── demand_usecases.py       ← Regras de negócio puras
│
├── infrastructure/                  ← Camada de dados
│   └── repositories/
│       └── sqlite_repository.py     ← Implementação SQLite
│
└── presentation/                    ← Interface gráfica PyQt6
    ├── windows/
    │   └── main_window.py           ← Janela principal + todas as views
    ├── dialogs/
    │   ├── demand_form.py           ← Formulário criar/editar demanda
    │   └── demand_detail.py         ← Detalhe + comentários + histórico
    ├── widgets/
    │   └── common_widgets.py        ← Badges, cards, gráficos reutilizáveis
    └── styles/
        └── stylesheet.py            ← Temas claro e escuro (QSS)
```

---

## ✨ Funcionalidades

### Dashboard
- Métricas em tempo real: abertas, atrasadas, concluídas, críticas
- Gráficos de barras por prioridade, status e categoria
- KPIs de horas e eficiência
- Lista de demandas recentes

### Lista de Demandas
- Filtros combinados: status, prioridade, categoria, responsável
- Busca por texto livre (título, descrição, tags, cliente)
- Cards com indicadores visuais de urgência e inatividade
- Progress bar de horas estimadas vs reais

### Kanban
- Colunas para cada status
- Cards clicáveis com prioridade e prazo
- Indicador de demandas atrasadas por coluna

### Calendário
- Visualização mensal com demandas nos dias de vencimento
- Painel lateral mostrando demandas da data selecionada

### Relatórios
- Tabela por responsável com taxa de conclusão
- KPIs gerais: horas, eficiência, taxa de conclusão
- Exportação PDF/Excel (integre reportlab/openpyxl)

### Base de Conhecimento
- Demandas concluídas automaticamente disponíveis como artigos
- Navegação por categoria e tags

### Sistema de Alertas
- Prazo vencido → borda vermelha no card
- Inatividade há 5+ dias → borda âmbar
- Painel de alertas acessível pelo sidebar
- Verificação automática a cada minuto

### Assistente de Produtividade
- "O que fazer hoje?" — entregas do dia
- "O que está mais atrasado?" — ranking por dias de atraso
- "Quais foram esquecidas?" — sem atividade há 10+ dias
- "O que consome mais tempo?" — top 5 por horas
- "Quantas críticas abertas?" — demandas críticas em aberto

### Detalhe da Demanda
- Alteração de status com um clique
- Atualização de horas trabalhadas
- Comentários por tipo: Comentário, Nota Técnica, Decisão, Reunião
- Histórico completo de alterações auditável
- Anexo de arquivos (PDF, Excel, imagens, etc.)

---

## 🗄️ Banco de Dados

O SQLite é criado em `~/.demandflow/demandflow.db`.

Tabelas:
- `demands` — todas as demandas
- `comments` — comentários e notas
- `history` — log de alterações
- `attachments` — arquivos anexados

### Migração para PostgreSQL (futuro)
Apenas substitua `SQLiteDemandRepository` por uma implementação PostgreSQL
que implemente a mesma interface `DemandRepository`. A camada de negócio
(core/) não muda nada.

---

## 🎨 Temas

Alterne entre **Tema Claro** e **Tema Escuro** pelo botão no sidebar inferior.
O tema é aplicado instantaneamente sem reiniciar.

---

## 🔮 Roadmap Futuro

- [ ] Integração com API Anthropic para sugestão automática de prioridade
- [ ] Notificações por e-mail / Slack
- [ ] Templates de demandas recorrentes
- [ ] Exportação PDF/Excel real (reportlab + openpyxl)
- [ ] Dependências visuais entre demandas
- [ ] Backup automático do banco de dados
- [ ] Migração para PostgreSQL
- [ ] Sincronização em nuvem
- [ ] App mobile (React Native com mesma API)
