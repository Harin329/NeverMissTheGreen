import * as path from "path";
import {
  CfnOutput,
  Duration,
  RemovalPolicy,
  Stack,
  StackProps,
} from "aws-cdk-lib";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import { HttpUserPoolAuthorizer } from "aws-cdk-lib/aws-apigatewayv2-authorizers";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Construct } from "constructs";

const LAMBDA_DIR = path.join(__dirname, "..", "lambda");
// every origin the site is served from must be a registered OAuth callback
const SITE_URLS = [
  "https://nevermissthegreen.netlify.app/",
  "https://nevermiss.harinwu.com/",
];

const FUNCTIONS: Record<string, string> = {
  getShot: "arn:aws:iam::146016028579:role/service-role/getShot-role-a3a2osyf",
  trackShot: "arn:aws:iam::146016028579:role/service-role/trackShot-role-cls2lwp1",
  updateShot: "arn:aws:iam::146016028579:role/service-role/updateShot-role-9e6levxj",
  deleteShot: "arn:aws:iam::146016028579:role/service-role/deleteShot-role-hs26kdot",
};

// [method, function, requiresJwt] — POST is authenticated by per-user device
// keys inside trackShot (iOS Shortcuts can't do OAuth), everything else by JWT.
const ROUTES: Array<[apigwv2.HttpMethod, string, boolean]> = [
  [apigwv2.HttpMethod.GET, "getShot", true],
  [apigwv2.HttpMethod.POST, "trackShot", false],
  [apigwv2.HttpMethod.PUT, "updateShot", true],
  [apigwv2.HttpMethod.DELETE, "deleteShot", true],
];

export class GolfShotStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    const table = new dynamodb.Table(this, "GolfShotsTable", {
      tableName: "golf_shots",
      partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    table.addGlobalSecondaryIndex({
      indexName: "AllShots",
      partitionKey: { name: "gsi1pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "gsi1sk", type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    const userPool = new cognito.UserPool(this, "Users", {
      userPoolName: "nevermissthegreen-users",
      selfSignUpEnabled: true,
      signInAliases: { email: true },
      autoVerify: { email: true },
      standardAttributes: { email: { required: true, mutable: false } },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const domain = userPool.addDomain("HostedDomain", {
      cognitoDomain: { domainPrefix: "nevermissthegreen" },
    });
    const webClient = userPool.addClient("WebClient", {
      authFlows: { userSrp: true },
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [
          cognito.OAuthScope.OPENID,
          cognito.OAuthScope.EMAIL,
          cognito.OAuthScope.PROFILE,
        ],
        callbackUrls: [...SITE_URLS, "http://localhost:8888/"],
        logoutUrls: [...SITE_URLS, "http://localhost:8888/"],
      },
      preventUserExistenceErrors: true,
    });
    const authorizer = new HttpUserPoolAuthorizer("UserPoolAuthorizer", userPool, {
      userPoolClients: [webClient],
    });

    const functions: Record<string, lambda.Function> = {};
    for (const [name, roleArn] of Object.entries(FUNCTIONS)) {
      const role = iam.Role.fromRoleArn(this, `${name}Role`, roleArn, {
        mutable: false,
      });
      const fn = new lambda.Function(this, `${name}Function`, {
        functionName: name,
        runtime: lambda.Runtime.PYTHON_3_12,
        handler: "lambda_function.lambda_handler",
        code: lambda.Code.fromAsset(path.join(LAMBDA_DIR, name)),
        role,
        timeout: Duration.seconds(3),
        memorySize: 128,
      });
      fn.applyRemovalPolicy(RemovalPolicy.RETAIN);
      functions[name] = fn;
    }

    const manageKeys = new lambda.Function(this, "manageKeysFunction", {
      functionName: "manageKeys",
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: "lambda_function.lambda_handler",
      code: lambda.Code.fromAsset(path.join(LAMBDA_DIR, "manageKeys")),
      timeout: Duration.seconds(5),
      memorySize: 128,
      environment: { TABLE_NAME: table.tableName },
    });
    table.grantReadWriteData(manageKeys);

    const api = new apigwv2.HttpApi(this, "ShotApi", {
      apiName: "shot",
      corsPreflight: {
        allowOrigins: ["*"],
        allowHeaders: ["content-type", "authorization", "x-api-key"],
        allowMethods: [apigwv2.CorsHttpMethod.ANY],
        allowCredentials: false,
        maxAge: Duration.seconds(0),
      },
    });
    api.applyRemovalPolicy(RemovalPolicy.RETAIN);
    (api.defaultStage!.node.defaultChild as apigwv2.CfnStage).applyRemovalPolicy(
      RemovalPolicy.RETAIN
    );

    for (const [method, fnName, requiresJwt] of ROUTES) {
      const routes = api.addRoutes({
        path: "/shot",
        methods: [method],
        integration: new HttpLambdaIntegration(
          `${fnName}Integration`,
          functions[fnName]
        ),
        authorizer: requiresJwt ? authorizer : undefined,
      });
      for (const route of routes) {
        route.applyRemovalPolicy(RemovalPolicy.RETAIN);
      }
    }

    api.addRoutes({
      path: "/keys",
      methods: [
        apigwv2.HttpMethod.GET,
        apigwv2.HttpMethod.POST,
        apigwv2.HttpMethod.DELETE,
      ],
      integration: new HttpLambdaIntegration("manageKeysIntegration", manageKeys),
      authorizer,
    });

    new CfnOutput(this, "UserPoolId", { value: userPool.userPoolId });
    new CfnOutput(this, "WebClientId", { value: webClient.userPoolClientId });
    new CfnOutput(this, "AuthDomain", { value: domain.baseUrl() });
    new CfnOutput(this, "ApiUrl", { value: api.apiEndpoint });
  }
}
