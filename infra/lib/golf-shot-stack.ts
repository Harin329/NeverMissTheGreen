import * as path from "path";
import { Duration, RemovalPolicy, Stack, StackProps } from "aws-cdk-lib";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Construct } from "constructs";

const LAMBDA_DIR = path.join(__dirname, "..", "lambda");

const FUNCTIONS: Record<string, string> = {
  getShot: "arn:aws:iam::146016028579:role/service-role/getShot-role-a3a2osyf",
  trackShot: "arn:aws:iam::146016028579:role/service-role/trackShot-role-cls2lwp1",
  updateShot: "arn:aws:iam::146016028579:role/service-role/updateShot-role-9e6levxj",
  deleteShot: "arn:aws:iam::146016028579:role/service-role/deleteShot-role-hs26kdot",
};

const ROUTES: Array<[apigwv2.HttpMethod, string]> = [
  [apigwv2.HttpMethod.GET, "getShot"],
  [apigwv2.HttpMethod.POST, "trackShot"],
  [apigwv2.HttpMethod.PUT, "updateShot"],
  [apigwv2.HttpMethod.DELETE, "deleteShot"],
];

export class GolfShotStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    new dynamodb.Table(this, "GolfShotsTable", {
      tableName: "golf_shots",
      partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: RemovalPolicy.RETAIN,
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

    const api = new apigwv2.HttpApi(this, "ShotApi", {
      apiName: "shot",
      corsPreflight: {
        allowOrigins: ["*"],
        allowHeaders: ["content-type"],
        allowMethods: [apigwv2.CorsHttpMethod.ANY],
        allowCredentials: false,
        maxAge: Duration.seconds(0),
      },
    });
    api.applyRemovalPolicy(RemovalPolicy.RETAIN);
    (api.defaultStage!.node.defaultChild as apigwv2.CfnStage).applyRemovalPolicy(
      RemovalPolicy.RETAIN
    );

    for (const [method, fnName] of ROUTES) {
      const routes = api.addRoutes({
        path: "/shot",
        methods: [method],
        integration: new HttpLambdaIntegration(
          `${fnName}Integration`,
          functions[fnName]
        ),
      });
      for (const route of routes) {
        route.applyRemovalPolicy(RemovalPolicy.RETAIN);
      }
    }
  }
}
