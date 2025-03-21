#
#  This needs to be modified and/or verified on Windows 10/11
#
# https://medium.com/@mreichelt/how-to-show-x11-windows-within-docker-on-mac-50759f4b65cb
##
#  Start Xquartz and ensure that "Allow connections from network clients" is enabled in settings:Security.  After you do
#  so restart Xquartz to load the settings (DUMB)
# 
#  then set xhost 
   xhost + 127.0.0.1     # ON the Mac host
#
#  create a docker bridge so that this instance can talk with another instance
#  First time it creates a bridge.  Other times just ignore the warning.  It's there and will connect :)
docker network create -d bridge my-net 
# then running is simple.  This will allow GUI use on OSx and will 
#  mount the vibb_sim directory in scratch for editing.  Use VSCode and pallet to select DEV containers: Open folder..
    docker run -it --network=my-net --mount type=bind,src=/Users/michaelbrooks/Desktop/Astraios/Dockerfiles/vibb_simulator,dst=/scratch/vibb_simulator -e DISPLAY=host.docker.internal:0 vibb-sim

# Check that it is working by running xclock
#   xclock



