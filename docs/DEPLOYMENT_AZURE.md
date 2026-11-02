# Deploying on Azure App Service (about 20 minutes, no command line)

> **Data rule:** in a personal / free-trial subscription use only the synthetic sample or anonymised data.
> Real VARD drawings require the app to run in the VARD/Fincantieri Azure tenant, with IT approval.

## 1. Subscription
Azure portal → **Start with an Azure free trial** → **Start**. You'll need a Microsoft account, a phone and a card for identity verification. You aren't charged unless you upgrade.

## 2. Create the Web App
Azure portal → **App Services** → **+ Create** → **Web App**.

| Field | Value |
|---|---|
| Subscription | your free trial |
| Resource group | **Create new** → `rg-scaffold-planner` |
| Name | e.g. `vsr-scaffold-planner` (gives https://vsr-scaffold-planner.azurewebsites.net, or a similar name with a suffix) |
| Publish | **Code** |
| Runtime stack | **Python 3.12** |
| Operating system | **Linux** |
| Region | **Italy North** (if not offered: West Europe or North Europe) |
| Pricing plan | **Basic B1**. Free F1 is too limited: 60 CPU minutes per day. |

**Review + create** → **Create**. Wait about 1 minute, then **Go to resource**.

## 3. Settings
1. Left menu → **Settings → Configuration** (or **Configuration → General settings**) → **Startup Command**: `bash startup.sh` → **Save**.
2. Left menu → **Settings → Environment variables** → **+ Add**:
   - `SCM_DO_BUILD_DURING_DEPLOYMENT` = `true`
   → **Apply** → **Confirm**.

## 4. Connect GitHub (deploys automatically on every push)
Left menu → **Deployment → Deployment Center**:
- Source: **GitHub** → **Authorize** (sign in to GitHub)
- Organization: `claudiotaboga` · Repository: `scaffolding_planner` · Branch: `main`
- Authentication type: **User-assigned identity** (default) → **Save**

Azure adds a GitHub Actions workflow to the repo and starts the first build and deploy (5–10 minutes). Progress is shown under **Deployment Center → Logs**, or in GitHub → **Actions**.

## 5. Protect it with Microsoft login (no code)
Left menu → **Settings → Authentication** → **Add identity provider**:
- Identity provider: **Microsoft**
- Tenant type: **Workforce** (current tenant) · App registration: **Create new** (defaults)
- Restrict access: **Require authentication** · Unauthenticated requests: **HTTP 302 redirect**
→ **Add**.

Only accounts in your Entra directory can now open the app. To give a colleague access: **Microsoft Entra ID → Users → New user → Invite external user**.

## 6. Open it
**Overview → Default domain** → open the URL. The first start takes about 1 minute and loads the sample block B12.

## Operations
- **Data** (projects, runs, uploaded drawings) is kept in `/home/data` on the App Service. It survives restarts and redeploys, and is included in App Service backups (**Settings → Backups**, available on Basic tier).
- **Update:** push to `main`; Azure redeploys automatically.
- **Logs:** **Monitoring → Log stream**.
- **Cost:** B1 runs continuously. To pause spending, **Overview → Stop**; the plan's compute charges stop only if you scale it down or delete it. Set a budget alert under **Cost Management → Budgets**.
- **DWG import** needs the ODA File Converter, which isn't on App Service by default. Import DXF or PDF on Azure, or convert DWG to DXF locally.

## Moving to the VARD tenant later
VARD IT creates the same Web App in their subscription and points Deployment Center to the repo. In Authentication they select the VARD Entra tenant. Nothing in the code changes. For many concurrent users, they can move the database to Azure Database for PostgreSQL (only `backend/vsr/store.py` changes).
