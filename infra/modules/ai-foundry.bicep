// ============================================================
// AI Foundry — account (AVM) + project + capability host + connections
//
// AVM covers the Cognitive Services account + model deployments + account-
// scoped RBAC + diagnostic settings. The Foundry *project*, *capabilityHost*,
// and project-scoped *connections* are not yet published as AVM sub-modules,
// so they are defined here as native child resources on an `existing`
// reference to the AVM-deployed account.
// ============================================================

targetScope = 'resourceGroup'

@description('Location for the Foundry account and deployments.')
param location string

@description('Tags applied to every resource in this module.')
param tags object = {}

@description('Name of the AI Foundry (AI Services) account.')
param aiFoundryAccountName string

@description('Name of the Foundry project.')
param aiFoundryProjectName string

@description('Deterministic token used for naming dependent resources (ACR, LAW, App Insights).')
param resourceToken string

@description('Object ID of the deploying user or service principal.')
param principalId string

@description('Principal type of the deploying identity.')
@allowed([ 'User', 'ServicePrincipal' ])
param principalType string = 'User'

@description('Model deployments on the Foundry account. AVM cognitive-services/account deployments[] schema.')
param deployments array = []

@description('When true, create Log Analytics + Application Insights (unless existing IDs are supplied).')
param enableMonitoring bool = true

@description('When true, enable the Foundry capability host for hosted agents and grant hosted-agent RBAC.')
param enableHostedAgents bool = false

@description('Optional existing Log Analytics workspace resource ID. When empty and monitoring is enabled, a new workspace is created.')
param existingLogAnalyticsResourceId string = ''

@description('Optional existing Application Insights resource ID. When empty and monitoring is enabled, a new component is created.')
param existingApplicationInsightsResourceId string = ''

@description('Optional existing Application Insights connection string. Only used when `existingApplicationInsightsResourceId` is supplied (since we cannot read the connection string of an existing component at deploy time).')
@secure()
param existingApplicationInsightsConnectionString string = ''

@description('Optional existing Container Registry resource ID (must be in the same resource group). When empty, a new ACR is created.')
param existingContainerRegistryResourceId string = ''

@description('Resource ID of the Azure AI Search service to connect to the project (empty disables the connection).')
param aiSearchResourceId string = ''

@description('Endpoint of the Azure AI Search service (e.g. https://srch-xyz.search.windows.net).')
param aiSearchEndpoint string = ''

@description('Name of the Azure AI Search service (used for RBAC scoping).')
param aiSearchName string = ''

// ============================================================
// Built-in role definition IDs
// ============================================================
var roles = {
  azureAiUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  azureAiDeveloper: '64702f94-c441-49e6-a78b-ef80e0188fee'
  cognitiveServicesUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
}

var shouldCreateLaw = enableMonitoring && empty(existingLogAnalyticsResourceId)
var shouldCreateAppi = enableMonitoring && empty(existingApplicationInsightsResourceId)
var shouldCreateAcr = empty(existingContainerRegistryResourceId)

// Deterministic name for the ACR we create. Computed from params so it can
// be used in if-conditions and guid() inputs (Bicep requires these at the start
// of a deployment, before any module outputs are available).
var containerRegistryNameEff = shouldCreateAcr ? 'acr${replace(resourceToken, '-', '')}' : last(split(existingContainerRegistryResourceId, '/'))
var containerRegistryLoginServerEff = '${containerRegistryNameEff}.azurecr.io'
var hasAcr = shouldCreateAcr || !empty(existingContainerRegistryResourceId)
var hasAppi = shouldCreateAppi || (!empty(existingApplicationInsightsResourceId) && !empty(existingApplicationInsightsConnectionString))

// ============================================================
// Log Analytics Workspace (AVM)
// ============================================================
module logAnalytics 'br/public:avm/res/operational-insights/workspace:0.15.0' = if (shouldCreateLaw) {
  name: 'law-${resourceToken}'
  params: {
    name: 'log-${resourceToken}'
    location: location
    tags: tags
    skuName: 'PerGB2018'
    dataRetention: 30
  }
}

var logAnalyticsResourceIdEff = shouldCreateLaw ? logAnalytics!.outputs.resourceId : existingLogAnalyticsResourceId

// ============================================================
// Application Insights (AVM)
// ============================================================
module applicationInsights 'br/public:avm/res/insights/component:0.7.1' = if (shouldCreateAppi) {
  name: 'appi-${resourceToken}'
  params: {
    name: 'appi-${resourceToken}'
    location: location
    tags: tags
    workspaceResourceId: logAnalyticsResourceIdEff
    kind: 'web'
    applicationType: 'web'
  }
}

var applicationInsightsResourceIdEff = shouldCreateAppi ? applicationInsights!.outputs.resourceId : existingApplicationInsightsResourceId
var applicationInsightsConnectionStringEff = shouldCreateAppi ? applicationInsights!.outputs.connectionString : existingApplicationInsightsConnectionString

// ============================================================
// Container Registry (AVM) — only when not supplying an existing one
// ============================================================
module containerRegistry 'br/public:avm/res/container-registry/registry:0.12.1' = if (shouldCreateAcr) {
  name: 'acr-${resourceToken}'
  params: {
    name: containerRegistryNameEff
    location: location
    tags: tags
    acrSku: 'Premium'
    acrAdminUserEnabled: false
    anonymousPullEnabled: false
    publicNetworkAccess: 'Enabled'
    networkRuleBypassOptions: 'AzureServices'
    networkRuleSetDefaultAction: 'Allow'
    exportPolicyStatus: 'enabled'
  }
}

var containerRegistryResourceIdEff = shouldCreateAcr ? containerRegistry!.outputs.resourceId : existingContainerRegistryResourceId

// ============================================================
// Foundry Account (AVM cognitive-services/account, kind=AIServices)
// ============================================================
module aiServicesAccount 'br/public:avm/res/cognitive-services/account:0.14.2' = {
  name: 'ai-foundry-account'
  params: {
    name: aiFoundryAccountName
    location: location
    tags: tags
    kind: 'AIServices'
    sku: 'S0'
    customSubDomainName: aiFoundryAccountName
    allowProjectManagement: true
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    managedIdentities: {
      systemAssigned: true
    }
    deployments: deployments
    diagnosticSettings: enableMonitoring ? [
      {
        name: 'default'
        workspaceResourceId: logAnalyticsResourceIdEff
      }
    ] : []
    roleAssignments: [
      {
        principalId: principalId
        principalType: principalType
        roleDefinitionIdOrName: roles.azureAiDeveloper
      }
      {
        principalId: principalId
        principalType: principalType
        roleDefinitionIdOrName: roles.cognitiveServicesUser
      }
    ]
  }
}

// ============================================================
// Foundry project (native child resource — no AVM module yet)
// ============================================================
resource aiAccountRef 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: aiFoundryAccountName
}

resource aiProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: aiAccountRef
  name: aiFoundryProjectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    description: '${aiFoundryProjectName} project'
    displayName: aiFoundryProjectName
  }
  dependsOn: [
    aiServicesAccount
  ]
}

// ============================================================
// Capability host (required for hosted agents)
// ============================================================
resource capabilityHost 'Microsoft.CognitiveServices/accounts/capabilityHosts@2025-10-01-preview' = if (enableHostedAgents) {
  parent: aiAccountRef
  name: 'agents'
  properties: {
    capabilityHostKind: 'Agents'
    // Enables hosted agents without bring-your-own VNet.
    enablePublicHostingEnvironment: true
  }
  dependsOn: [
    aiServicesAccount
  ]
}

// ============================================================
// Project connections: App Insights + ACR
// ============================================================
resource appiConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = if (hasAppi) {
  parent: aiProject
  name: 'appi-connection'
  properties: {
    category: 'AppInsights'
    target: shouldCreateAppi ? applicationInsights!.outputs.resourceId : existingApplicationInsightsResourceId
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: {
      key: shouldCreateAppi ? applicationInsights!.outputs.connectionString : existingApplicationInsightsConnectionString
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: shouldCreateAppi ? applicationInsights!.outputs.resourceId : existingApplicationInsightsResourceId
    }
  }
}

resource acrConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = if (hasAcr) {
  parent: aiProject
  name: 'acr-connection'
  properties: {
    category: 'ContainerRegistry'
    target: containerRegistryLoginServerEff
    authType: 'ManagedIdentity'
    isSharedToAll: true
    credentials: {
      clientId: aiProject.identity.principalId
      resourceId: containerRegistryResourceIdEff
    }
    metadata: {
      ResourceId: containerRegistryResourceIdEff
    }
  }
}

// Azure AI Search — backs Foundry IQ / Agent Knowledge. AAD auth via the
// project MI; the RBAC role assignments below grant the project read+write
// access to indexes on this search service.
resource searchConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = if (!empty(aiSearchResourceId)) {
  parent: aiProject
  name: 'search-connection'
  properties: {
    category: 'CognitiveSearch'
    target: aiSearchEndpoint
    authType: 'AAD'
    isSharedToAll: true
    metadata: {
      ApiType: 'Azure'
      ResourceId: aiSearchResourceId
    }
  }
}

// ============================================================
// Project-identity RBAC on the Foundry account
// ============================================================
resource projectAiUserOnAccount 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aiAccountRef
  name: guid(aiAccountRef.id, aiProject.id, roles.azureAiUser)
  properties: {
    principalId: aiProject.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.azureAiUser)
  }
}

resource projectAiDeveloperOnAccount 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enableHostedAgents) {
  scope: aiAccountRef
  name: guid(aiAccountRef.id, aiProject.id, roles.azureAiDeveloper)
  properties: {
    principalId: aiProject.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.azureAiDeveloper)
  }
}

// ============================================================
// Account-identity RBAC on itself (hosted agent runtime needs it)
// ============================================================
resource accountMiCogUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enableHostedAgents) {
  scope: aiAccountRef
  name: guid(aiAccountRef.id, 'account-mi', roles.cognitiveServicesUser)
  properties: {
    principalId: aiServicesAccount.outputs.systemAssignedMIPrincipalId!
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesUser)
  }
}

resource accountMiAiDeveloper 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enableHostedAgents) {
  scope: aiAccountRef
  name: guid(aiAccountRef.id, 'account-mi', roles.azureAiDeveloper)
  properties: {
    principalId: aiServicesAccount.outputs.systemAssignedMIPrincipalId!
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.azureAiDeveloper)
  }
}

// ============================================================
// AcrPull for the project MI (so hosted agent containers can pull images)
// Scoped to the ACR resource in this resource group. Cross-RG existing ACRs
// must be granted AcrPull manually.
// ============================================================
resource acrRef 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = if (hasAcr) {
  name: containerRegistryNameEff
}

resource acrPullForProject 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (hasAcr) {
  scope: acrRef
  name: guid(resourceGroup().id, containerRegistryNameEff, aiProject.id, roles.acrPull)
  properties: {
    principalId: aiProject.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
  }
}

// Also AcrPull for the account MI (some hosted-agent configs run under the account identity)
resource acrPullForAccount 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (hasAcr && enableHostedAgents) {
  scope: acrRef
  name: guid(resourceGroup().id, containerRegistryNameEff, 'account-mi', roles.acrPull)
  properties: {
    principalId: aiServicesAccount.outputs.systemAssignedMIPrincipalId!
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
  }
}

// ============================================================
// RBAC on the Azure AI Search service for the project MI.
// Search Index Data Contributor: create/read/write index docs.
// Search Service Contributor:    manage indexes/indexers/skillsets.
// ============================================================
resource searchRef 'Microsoft.Search/searchServices@2024-06-01-preview' existing = if (!empty(aiSearchName)) {
  name: aiSearchName
}

resource projectSearchIndexDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(aiSearchResourceId)) {
  scope: searchRef
  name: guid(aiSearchResourceId, aiProject.id, roles.searchIndexDataContributor)
  properties: {
    principalId: aiProject.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataContributor)
  }
}

resource projectSearchServiceContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(aiSearchResourceId)) {
  scope: searchRef
  name: guid(aiSearchResourceId, aiProject.id, roles.searchServiceContributor)
  properties: {
    principalId: aiProject.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchServiceContributor)
  }
}

// Also grant the deploying user data-plane access so they can manage indexes from the portal / SDK.
resource userSearchIndexDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(aiSearchResourceId)) {
  scope: searchRef
  name: guid(aiSearchResourceId, principalId, roles.searchIndexDataContributor)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataContributor)
  }
}

// ============================================================
// Outputs
// ============================================================
output accountId string = aiServicesAccount.outputs.resourceId
output accountName string = aiServicesAccount.outputs.name
output accountPrincipalId string = aiServicesAccount.outputs.systemAssignedMIPrincipalId!
output projectId string = aiProject.id
output projectName string = aiProject.name
output projectPrincipalId string = aiProject.identity.principalId
output projectEndpoint string = aiProject.properties.endpoints['AI Foundry API']
output openAiEndpoint string = aiServicesAccount.outputs.endpoint

output logAnalyticsResourceId string = logAnalyticsResourceIdEff
output applicationInsightsResourceId string = applicationInsightsResourceIdEff
@description('Application Insights connection string. Empty when an existing App Insights is supplied without its connection string.')
#disable-next-line outputs-should-not-contain-secrets
output applicationInsightsConnectionString string = applicationInsightsConnectionStringEff

output containerRegistryResourceId string = containerRegistryResourceIdEff
output containerRegistryLoginServer string = containerRegistryLoginServerEff
output containerRegistryName string = containerRegistryNameEff
