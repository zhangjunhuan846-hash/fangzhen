#!/bin/sh
set -e
python figure_1.py > output.txt
echo "--------------- End of script ---------------" >> output.txt
python figure_2.py >> output.txt
echo "--------------- End of script ---------------" >> output.txt
python figure_3_prep.py >> output.txt
echo "--------------- End of script ---------------" >> output.txt
python figure_3.py >> output.txt
echo "--------------- End of script ---------------" >> output.txt
python figure_4.py >> output.txt
echo "--------------- End of script ---------------" >> output.txt
python figure_5_prep.py >> output.txt
echo "--------------- End of script ---------------" >> output.txt
python figure_5.py >> output.txt
echo "--------------- End of script ---------------" >> output.txt
python figure_6.py >> output.txt
echo "--------------- End of script ---------------" >> output.txt
python figure_D0_prep.py >> output.txt
echo "--------------- End of script ---------------" >> output.txt
python figure_D1_prep.py >> output.txt
echo "--------------- End of script ---------------" >> output.txt
python figure_D1.py >> output.txt
echo "--------------- End of script ---------------" >> output.txt
python figure_D2_prep.py >> output.txt
echo "--------------- End of script ---------------" >> output.txt
python figure_D2.py >> output.txt
echo "--------------- End of script ---------------" >> output.txt
python figure_D3_prep.py >> output.txt
echo "--------------- End of script ---------------" >> output.txt
python figure_D3.py >> output.txt
