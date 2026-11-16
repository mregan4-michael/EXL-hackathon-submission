# Built from generated/<app>/src (context) so Domain and Api are both in scope.
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY Domain/ Domain/
COPY Api/ Api/
RUN dotnet publish Api/Factory.Api.csproj -c Release -o /app

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app .
ENV Seed__Path=/app/seed.json Store__Path=/data
USER $APP_UID
EXPOSE 8080
ENTRYPOINT ["dotnet", "Factory.Api.dll"]
