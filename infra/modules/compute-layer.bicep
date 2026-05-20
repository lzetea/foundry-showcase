// ============================================================
// Compute layer — ACA environment + MAF agent + LangGraph agent + Cosmos + Key Vault + optional APIM
// All resources use Azure Verified Modules (AVM).
// ============================================================

targetScope = 'resourceGroup'

@description('Primary location for compute resources.')
param location string

@description('Tags applied to every resource.')
param tags object = {}

@description('Deterministic naming token.')
param resourceToken string

@description('Log Analytics workspace resource ID for ACA diagnostics.')
param logAnalyticsResourceId string

@description('Application Insights connection string surfaced to container apps as APPLICATIONINSIGHTS_CONNECTION_STRING.')
@secure()
param applicationInsightsConnectionString string

@description('Application Insights resource ID (used by APIM logger).')
param applicationInsightsResourceId string = ''

@description('Foundry account resource ID (for RBAC scoping).')
param aiFoundryAccountId string

@description('Foundry account name (used for existing-reference lookup).')
param aiFoundryAccountName string

@description('Foundry project name (used to attach APIM as a project connection).')
param aiFoundryProjectName string

@description('Foundry project AI Foundry API endpoint (for agent runtime).')
param aiFoundryProjectEndpoint string

@description('Container Registry resource ID.')
param containerRegistryResourceId string

@description('Container Registry login server (e.g. myacr.azurecr.io).')
param containerRegistryLoginServer string

@description('MAF agent container image. When empty, the container app is provisioned with a public placeholder image and becomes functional once the per-scenario deploy script rolls the real image.')
param mafContainerImage string = ''

@description('LangGraph agent container image. When empty, the container app is provisioned with a public placeholder image and becomes functional once the per-scenario deploy script rolls the real image.')
param langGraphContainerImage string = ''

@description('Model deployment name passed to hosted agents.')
param modelDeploymentName string = 'gpt-5'

@description('Publisher email for APIM. Empty disables APIM.')
param apimPublisherEmail string = ''

@description('Publisher name for APIM.')
param apimPublisherName string = 'Agent Observability Demo'

@description('Token-per-minute cap enforced by APIM on the Azure OpenAI surface.')
param apimTokenLimitTpm int = 100000

@description('Azure OpenAI API version to import into APIM as an OpenAPI link.')
param apimOpenAiApiVersion string = '2024-10-21'

@description('Optional audience for AAD token validation on /agents (e.g. Foundry app id or custom API registration). Empty disables JWT validation.')
param apimAgentsJwtAudience string = ''

@description('Tenant ID for AAD token validation on /agents. Defaults to the deployment tenant.')
param apimAgentsJwtTenantId string = tenant().tenantId

@description('When true, APIM subscription keys are persisted to Key Vault and injected into container apps as opt-in AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY env vars. Agents keep using AAD auth by default; flip their code to honour the api-key to route through APIM.')
param apimSecretsToKeyVault bool = true

// ============================================================
// Role IDs
// ============================================================
var roles = {
  azureAiUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  cognitiveServicesUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  cosmosDbDataContributor: '00000000-0000-0000-0000-000000000002' // Built-in Cosmos SQL Data Contributor (data-plane)
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
}

// ============================================================
// User-Assigned Managed Identity — shared by both container apps.
// UAI lets us assign RBAC *before* the container app exists, avoiding cold-start auth races.
// ============================================================
module appsIdentity 'br/public:avm/res/managed-identity/user-assigned-identity:0.5.0' = {
  name: 'uai-apps-${resourceToken}'
  params: {
    name: 'id-apps-${resourceToken}'
    location: location
    tags: tags
  }
}

// ============================================================
// Key Vault
// ============================================================
var keyVaultName = 'kv-${take(resourceToken, 20)}'

module keyVault 'br/public:avm/res/key-vault/vault:0.13.3' = {
  name: 'kv-${resourceToken}'
  params: {
    name: keyVaultName
    location: location
    tags: tags
    sku: 'standard'
    enableRbacAuthorization: true
    enablePurgeProtection: false // PoC: allow easy teardown
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}

// ============================================================
// Cosmos DB (SQL API)
// ============================================================
module cosmos 'br/public:avm/res/document-db/database-account:0.19.0' = {
  name: 'cosmos-${resourceToken}'
  params: {
    name: 'cosmos-${resourceToken}'
    location: location
    tags: tags
    disableLocalAuthentication: true
    capabilitiesToAdd: [ 'EnableServerless' ]
    failoverLocations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    sqlDatabases: [
      {
        name: 'agents'
        containers: [
          {
            name: 'conversations'
            paths: [ '/sessionId' ]
          }
        ]
      }
    ]
    sqlRoleAssignments: [
      {
        principalId: appsIdentity.outputs.principalId
        roleDefinitionId: roles.cosmosDbDataContributor
      }
    ]
  }
}

// ============================================================
// Container Apps Environment
// AVM's appLogsConfiguration.logAnalyticsWorkspaceResourceId takes a LAW
// resource ID and handles listing the shared key internally.
// ============================================================
module acaEnvironment 'br/public:avm/res/app/managed-environment:0.13.2' = {
  name: 'cae-${resourceToken}'
  params: {
    name: 'cae-${resourceToken}'
    location: location
    tags: tags
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsWorkspaceResourceId: logAnalyticsResourceId
    }
    zoneRedundant: false
    publicNetworkAccess: 'Enabled'
  }
}

// ============================================================
// RBAC on the Foundry account for the apps UAI — needed for agent calls.
// ============================================================
resource aiAccountRef 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: aiFoundryAccountName
}

resource appsAiUserOnFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aiAccountRef
  name: guid(aiFoundryAccountId, resourceGroup().id, 'apps-uai', roles.azureAiUser)
  properties: {
    principalId: appsIdentity.outputs.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.azureAiUser)
  }
}

// AcrPull for the UAI so ACA can pull agent images from ACR.
resource acrRef 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: last(split(containerRegistryResourceId, '/'))
}

resource appsAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acrRef
  name: guid(containerRegistryResourceId, resourceGroup().id, 'apps-uai', roles.acrPull)
  properties: {
    principalId: appsIdentity.outputs.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
  }
}

// ============================================================
// Shared container app env vars
// ============================================================
var commonEnvVars = [
  { name: 'AZURE_AI_PROJECT_ENDPOINT', value: aiFoundryProjectEndpoint }
  { name: 'MODEL_DEPLOYMENT_NAME', value: modelDeploymentName }
  { name: 'COSMOS_ENDPOINT', value: cosmos.outputs.endpoint }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'appinsights-connection-string' }
  { name: 'AZURE_CLIENT_ID', value: appsIdentity.outputs.clientId }
]

var commonSecrets = [
  {
    name: 'appinsights-connection-string'
    value: applicationInsightsConnectionString
  }
]

// Placeholder image used when a scenario's real image hasn't been built yet.
// Keeps the ACA app resource (and therefore its FQDN) stable across the
// `azd up` → build → roll cycle so APIM backends resolve on the first pass.
// The placeholder listens on port 80; ACA probes on 8088 will fail until the
// real image is rolled by the per-scenario deploy script — that's expected.
var placeholderContainerImage = 'mcr.microsoft.com/k8se/quickstart:latest'
var effectiveMafImage = !empty(mafContainerImage) ? mafContainerImage : placeholderContainerImage
var effectiveLangGraphImage = !empty(langGraphContainerImage) ? langGraphContainerImage : placeholderContainerImage

// ============================================================
// MAF Agent container app
// ============================================================
module mafApp 'br/public:avm/res/app/container-app:0.22.1' = {
  name: 'ca-maf-${resourceToken}'
  params: {
    name: 'ca-maf-agent'
    location: location
    tags: union(tags, { 'azd-service-name': 'maf-agent' })
    environmentResourceId: acaEnvironment.outputs.resourceId
    managedIdentities: {
      userAssignedResourceIds: [ appsIdentity.outputs.resourceId ]
    }
    registries: [
      {
        server: containerRegistryLoginServer
        identity: appsIdentity.outputs.resourceId
      }
    ]
    ingressExternal: true
    ingressTargetPort: 8088
    ingressTransport: 'auto'
    scaleSettings: {
      minReplicas: 0
      maxReplicas: 3
    }
    secrets: commonSecrets
    containers: [
      {
        name: 'maf-agent'
        image: effectiveMafImage
        resources: {
          cpu: json('0.5')
          memory: '1Gi'
        }
        env: commonEnvVars
      }
    ]
  }
}

// ============================================================
// LangGraph Agent container app
// ============================================================
module langGraphApp 'br/public:avm/res/app/container-app:0.22.1' = {
  name: 'ca-lg-${resourceToken}'
  params: {
    name: 'ca-langgraph-agent'
    location: location
    tags: union(tags, { 'azd-service-name': 'langgraph-agent' })
    environmentResourceId: acaEnvironment.outputs.resourceId
    managedIdentities: {
      userAssignedResourceIds: [ appsIdentity.outputs.resourceId ]
    }
    registries: [
      {
        server: containerRegistryLoginServer
        identity: appsIdentity.outputs.resourceId
      }
    ]
    ingressExternal: true
    ingressTargetPort: 8088
    ingressTransport: 'auto'
    scaleSettings: {
      minReplicas: 0
      maxReplicas: 3
    }
    secrets: commonSecrets
    containers: [
      {
        name: 'langgraph-agent'
        image: effectiveLangGraphImage
        resources: {
          cpu: json('0.5')
          memory: '1Gi'
        }
        env: commonEnvVars
      }
    ]
  }
}

// ============================================================
// APIM (optional AI Gateway)
// ============================================================
module apim 'br/public:avm/res/api-management/service:0.14.1' = if (!empty(apimPublisherEmail)) {
  name: 'apim-${resourceToken}'
  params: {
    name: 'apim-${resourceToken}'
    location: location
    tags: tags
    publisherEmail: apimPublisherEmail
    publisherName: apimPublisherName
    sku: 'StandardV2'
    skuCapacity: 1
    managedIdentities: {
      systemAssigned: true
    }
  }
}

// APIM MI needs Cognitive Services User to call Foundry models.
resource apimCogUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(apimPublisherEmail)) {
  scope: aiAccountRef
  name: guid(aiFoundryAccountId, 'apim', roles.cognitiveServicesUser)
  properties: {
    principalId: apim!.outputs.systemAssignedMIPrincipalId!
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesUser)
  }
}

// ============================================================
// Existing Application Insights reference — needed for APIM logger (instrumentation key).
// ============================================================
resource appInsightsRef 'Microsoft.Insights/components@2020-02-02' existing = if (!empty(apimPublisherEmail) && !empty(applicationInsightsResourceId)) {
  name: last(split(applicationInsightsResourceId, '/'))
  scope: resourceGroup(split(applicationInsightsResourceId, '/')[2], split(applicationInsightsResourceId, '/')[4])
}

// ============================================================
// APIM AI Gateway configuration (APIs, backends, policies, logger, products, subscriptions)
// ============================================================
module apimGateway 'apim-ai-gateway.bicep' = if (!empty(apimPublisherEmail)) {
  name: 'apim-gw-${resourceToken}'
  params: {
    apimName: apim!.outputs.name
    aiFoundryAccountName: aiFoundryAccountName
    mafAgentFqdn: mafApp.outputs.fqdn
    langGraphAgentFqdn: langGraphApp.outputs.fqdn
    applicationInsightsResourceId: applicationInsightsResourceId
    applicationInsightsInstrumentationKey: !empty(applicationInsightsResourceId) ? appInsightsRef!.properties.InstrumentationKey : ''
    openAiApiVersion: apimOpenAiApiVersion
    tokenLimitTpm: apimTokenLimitTpm
    agentsJwtAudience: apimAgentsJwtAudience
    agentsJwtTenantId: apimAgentsJwtTenantId
    keyVaultName: apimSecretsToKeyVault ? keyVault.outputs.name : ''
  }
}

// Apps UAI needs Key Vault Secrets User so ACA secretRef bindings can resolve the APIM sub keys.
resource appsKvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (apimSecretsToKeyVault && !empty(apimPublisherEmail)) {
  scope: kvRef
  name: guid(resourceGroup().id, keyVaultName, 'apps-uai', roles.keyVaultSecretsUser)
  properties: {
    principalId: appsIdentity.outputs.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
  }
}

resource kvRef 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

// ============================================================
// Foundry project connections — surface APIM + agent routes as
// first-class connected resources in the Foundry portal.
// ============================================================
resource aiAccountForConn 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: aiFoundryAccountName
}

resource aiProjectForConn 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' existing = {
  parent: aiAccountForConn
  name: aiFoundryProjectName
}

// APIM OpenAI gateway as an AzureOpenAI connection — lets Foundry treat the
// APIM surface as the primary OpenAI endpoint, so all token metering flows
// through the gateway policies.
resource apimServiceRef 'Microsoft.ApiManagement/service@2024-06-01-preview' existing = if (!empty(apimPublisherEmail)) {
  name: 'apim-${resourceToken}'
}

resource apimOpenAiSubRef 'Microsoft.ApiManagement/service/subscriptions@2024-06-01-preview' existing = if (!empty(apimPublisherEmail)) {
  parent: apimServiceRef
  name: 'foundry-openai-sub'
}

resource apimAgentsSubRef 'Microsoft.ApiManagement/service/subscriptions@2024-06-01-preview' existing = if (!empty(apimPublisherEmail) && (!empty(mafContainerImage) || !empty(langGraphContainerImage))) {
  parent: apimServiceRef
  name: 'foundry-agents-sub'
}

resource foundryApimOpenAiConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = if (!empty(apimPublisherEmail)) {
  parent: aiProjectForConn
  name: 'apim-openai-gateway'
  properties: {
    category: 'AzureOpenAI'
    target: apimGateway!.outputs.openAiGatewayUrl
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: {
      key: apimOpenAiSubRef!.listSecrets().primaryKey
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: apim!.outputs.resourceId
    }
  }
}

// External agent routes as generic CustomKeys connections — surfaces the
// APIM-backed agent URLs in the Foundry portal's connected resources list.
resource foundryApimMafAgentConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = if (!empty(apimPublisherEmail) && !empty(mafContainerImage)) {
  parent: aiProjectForConn
  name: 'apim-agent-maf'
  properties: {
    category: 'CustomKeys'
    target: apimGateway!.outputs.mafAgentApimUrl
    authType: 'CustomKeys'
    isSharedToAll: true
    credentials: {
      keys: {
        'Ocp-Apim-Subscription-Key': apimAgentsSubRef!.listSecrets().primaryKey
      }
    }
    metadata: {
      ResourceId: apim!.outputs.resourceId
    }
  }
}

resource foundryApimLangGraphAgentConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = if (!empty(apimPublisherEmail) && !empty(langGraphContainerImage)) {
  parent: aiProjectForConn
  name: 'apim-agent-langgraph'
  properties: {
    category: 'CustomKeys'
    target: apimGateway!.outputs.langGraphAgentApimUrl
    authType: 'CustomKeys'
    isSharedToAll: true
    credentials: {
      keys: {
        'Ocp-Apim-Subscription-Key': apimAgentsSubRef!.listSecrets().primaryKey
      }
    }
    metadata: {
      ResourceId: apim!.outputs.resourceId
    }
  }
}

// ============================================================
// Outputs
// ============================================================
output appsIdentityResourceId string = appsIdentity.outputs.resourceId
output appsIdentityPrincipalId string = appsIdentity.outputs.principalId
output appsIdentityClientId string = appsIdentity.outputs.clientId

output acaEnvironmentResourceId string = acaEnvironment.outputs.resourceId
output acaEnvironmentName string = acaEnvironment.outputs.name

output mafAgentFqdn string = mafApp.outputs.fqdn
output langGraphAgentFqdn string = langGraphApp.outputs.fqdn

output cosmosEndpoint string = cosmos.outputs.endpoint
output cosmosName string = cosmos.outputs.name

output keyVaultUri string = keyVault.outputs.uri
output keyVaultResourceId string = keyVault.outputs.resourceId

output apimGatewayUrl string = !empty(apimPublisherEmail) ? 'https://${apim!.outputs.name}.azure-api.net' : ''
output apimName string = !empty(apimPublisherEmail) ? apim!.outputs.name : ''
output apimMafAgentUrl string = !empty(apimPublisherEmail) ? apimGateway!.outputs.mafAgentApimUrl : ''
output apimLangGraphAgentUrl string = !empty(apimPublisherEmail) ? apimGateway!.outputs.langGraphAgentApimUrl : ''
output apimOpenAiGatewayUrl string = !empty(apimPublisherEmail) ? apimGateway!.outputs.openAiGatewayUrl : ''
output apimAgentsSubscriptionResourceId string = !empty(apimPublisherEmail) ? apimGateway!.outputs.agentsSubscriptionResourceId : ''
output apimOpenAiSubscriptionResourceId string = !empty(apimPublisherEmail) ? apimGateway!.outputs.openAiSubscriptionResourceId : ''
output apimOpenAiKeySecretName string = !empty(apimPublisherEmail) && apimSecretsToKeyVault ? apimGateway!.outputs.openAiKeySecretName : ''
output apimAgentsKeySecretName string = !empty(apimPublisherEmail) && apimSecretsToKeyVault ? apimGateway!.outputs.agentsKeySecretName : ''
