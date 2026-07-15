#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { GolfShotStack } from "../lib/golf-shot-stack";

const app = new cdk.App();
new GolfShotStack(app, "GolfShotStack", {
  env: { account: "146016028579", region: "us-east-1" },
});
