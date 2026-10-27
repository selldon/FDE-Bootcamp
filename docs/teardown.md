# Teardown of the deploy

What to run when the pilot's server is no longer needed, in order, and what each command removes. The account owner runs
them; the deploy role may run only steps 2 and 3 (it can terminate the tagged server and read EC2). Region `us-east-1`.

    export AWS_REGION=us-east-1
    ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"

## 0. Stop new deploys first

    gh workflow disable deploy --repo termidy/FDE-Bootcamp

Removes nothing. Every merge to `main` runs the deploy, and with the role still in place it would start a new server (or
start this one again). Do this before step 2 and enable it again (`gh workflow enable deploy`) only if you want the server back.

## 1. Save the shadow report (the restore point of step 2)

    gh workflow run deploy --ref main -f report=true --repo termidy/FDE-Bootcamp

Open the run, copy the `deploy` job's output (the 20 newest chats) into a file outside git. Removes nothing. The report shows
only 20 rows: older shadow rows exist only in the server's PostgreSQL and are lost with step 2.

## 2. Terminate the server (the deploy role may)

First look at what you are about to remove; it must carry the tag and be the one instance:

    aws ec2 describe-instances --filters Name=tag:project,Values=fde-course Name=instance-state-name,Values=pending,running,stopping,stopped \
      --query 'Reservations[].Instances[].[InstanceId,InstanceType,State.Name]' --output text
    aws ec2 terminate-instances --instance-ids i-0c9d3c513e33f485c

Removes: the instance `i-0c9d3c513e33f485c` (tag `project=fde-course`), its 30 GB disk (`DeleteOnTermination=true`) and with
them every container, the images pulled to it, DemoStore's systems, the order store, the policy index and **all shadow rows**.
Cannot be undone. If the first command shows another id, use that one. The Anthropic key stays in SSM (step 4).

## 3. Check it is gone (the deploy role may)

    aws ec2 describe-instances --filters Name=tag:project,Values=fde-course \
      --query 'Reservations[].Instances[].[InstanceId,State.Name]' --output text      # terminated
    aws ec2 describe-volumes --filters Name=tag:project,Values=fde-course \
      --query 'Volumes[].VolumeId' --output text                                      # nothing

## 4. What is left in the account (a person's job; the role cannot)

Each command names what it deletes. Costs after step 2 are small (ECR storage), but the pieces stay until removed.

    # the two image repositories and every image in them
    aws ecr delete-repository --repository-name fde-course/demostore-app --force
    aws ecr delete-repository --repository-name fde-course/demostore-widget --force

    # the Anthropic key (SecureString). If it is not used elsewhere, revoke it in the Anthropic console too
    aws ssm delete-parameter --name /fde-course/anthropic-api-key

    # the server's role and instance profile, both named fde-course-ec2: look at its policies, then remove
    aws iam list-attached-role-policies --role-name fde-course-ec2
    aws iam list-role-policies --role-name fde-course-ec2
    #   detach each listed managed policy:  aws iam detach-role-policy --role-name fde-course-ec2 --policy-arn <arn from the list>
    #   delete each listed inline policy:   aws iam delete-role-policy --role-name fde-course-ec2 --policy-name <name from the list>
    aws iam remove-role-from-instance-profile --instance-profile-name fde-course-ec2 --role-name fde-course-ec2
    aws iam delete-instance-profile --instance-profile-name fde-course-ec2
    aws iam delete-role --role-name fde-course-ec2

    # the deploy role fde-course-deploy, the same way
    aws iam list-attached-role-policies --role-name fde-course-deploy
    aws iam list-role-policies --role-name fde-course-deploy
    #   detach / delete each one listed, as above, then:
    aws iam delete-role --role-name fde-course-deploy

    # the GitHub OIDC provider: ONLY if no other role in the account trusts it
    aws iam delete-open-id-connect-provider --open-id-connect-provider-arn "arn:aws:iam::$ACCOUNT:oidc-provider/token.actions.githubusercontent.com"

    # the repository variable that named the deploy role
    gh variable delete AWS_DEPLOY_ROLE_ARN --repo termidy/FDE-Bootcamp

Not touched: the account's default VPC and default security group (the deploy only read the group), and the pull requests,
workflow runs and logs in GitHub.
