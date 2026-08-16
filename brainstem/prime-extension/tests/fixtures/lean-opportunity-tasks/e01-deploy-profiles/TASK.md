# TASK — e01-deploy-profiles

We are adding a staging environment to our deploy flow. Deploys go through deploy.js, which reads environment profiles from config/profiles.json. Staging should use a 15-second timeout while production keeps its 30-second timeout. Make `node deploy.js staging` work the same way `node deploy.js prod` works today.
